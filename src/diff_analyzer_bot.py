import os
import json
import re
from datetime import datetime
import discord
from discord.ext import commands
from dotenv import load_dotenv
from groq import AsyncGroq
from config_loader import load_config

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Load YAML Config
config = load_config()
TARGET_CHANNEL_ID = config.get("discord", {}).get("target_channel_id")

DISCORD_USER_MAPPINGS = {}
for key, user_data in config.get("users", {}).items():
    shortcode = user_data["shortcode"]
    discord_username = user_data["discord_username"]
    DISCORD_USER_MAPPINGS[shortcode] = discord_username

# Initialize Discord Intents & Bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  
bot = commands.Bot(command_prefix="!", intents=intents)

# Initialize Groq Async Client
groq_client = AsyncGroq(api_key=GROQ_API_KEY)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"Monitoring and formatting channel ID: {TARGET_CHANNEL_ID}")
    print("------")

# Dictionary to buffer multi-part diffs from the webhook
diff_buffers = {}

@bot.event
async def on_message(message):
    # 1. Ignore messages sent by the bot itself
    if message.author == bot.user:
        return

    # 2. Check if the message is in the target channel
    if message.channel.id == TARGET_CHANNEL_ID:
        
        # Extract text from message content OR embeds (Crucial for the Code Output APP)
        extracted_text = message.content or ""
        if message.embeds:
            for embed in message.embeds:
                if embed.title:
                    extracted_text += f"\n{embed.title}"
                if embed.description:
                    extracted_text += f"\n{embed.description}"
                for field in embed.fields:
                    extracted_text += f"\n{field.name}\n{field.value}"
                    
        extracted_text = extracted_text.strip()

        if extracted_text:
            author_id = message.author.id
            
            # Initialize buffer for this webhook if it doesn't exist
            if author_id not in diff_buffers:
                diff_buffers[author_id] = ""

            # DELETE MESSAGE EARLY: Catch 404s so it doesn't crash if already deleted
            try:
                await message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

            # BUFFERING LOGIC
            if "[END OF DIFF]" not in extracted_text:
                # Append chunk and STOP. Wait for the next one.
                diff_buffers[author_id] += f"\n{extracted_text}"
                return 
            
            # End signal received! Clean it and finalize the buffer
            clean_text = extracted_text.replace("[END OF DIFF]", "").strip()
            if clean_text:
                diff_buffers[author_id] += f"\n{clean_text}"
            
            # Retrieve the fully assembled diff and instantly clear the buffer
            full_diff_text = diff_buffers[author_id].strip()
            diff_buffers[author_id] = ""

            if not full_diff_text:
                await message.channel.send(f"{message.author.mention} ⚠️ **Diff Processing Error:** Received the end signal, but the buffer was empty.")
                return

            try:
                # Determine user mention
                mapped_mention = message.author.mention
                for shortcode, discord_username in DISCORD_USER_MAPPINGS.items():
                    if shortcode in full_diff_text:
                        if message.guild:
                            found_member = discord.utils.find(
                                lambda m: m.name.lower() == discord_username.lower() or 
                                          (m.global_name and m.global_name.lower() == discord_username.lower()),
                                message.guild.members
                            )
                            if found_member:
                                mapped_mention = found_member.mention
                            else:
                                mapped_mention = f"@{discord_username}"
                        break

                print(f"--- Processing new diff ---\nExtracted {len(full_diff_text)} characters.")

                async with message.channel.typing():
                    # Call API with higher max_tokens to prevent cut-offs
                    chat_completion = await groq_client.chat.completions.create(
                        model="openai/gpt-oss-20b",
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    "You are an expert developer assistant. Analyze the provided git diff (which includes metadata at the top) and output a valid JSON object. "
                                    "The JSON object must contain exactly these three keys:\n\n"
                                    "\"lines\": The exact count of lines added and removed (e.g., '+15/-3').\n\n"
                                    "\"commit\": The commit message formatted with literal '\\n' characters for line breaks. You MUST adhere strictly to these rules:\n"
                                    "1. Find 'Shortcode: ' in the metadata and extract the exact value. Start your message with this value wrapped in brackets (e.g., [mb1425]). Do NOT output empty brackets [ ].\n"
                                    "2. Write the subject and ALL bullet points in the imperative, present-tense command form (e.g., 'Add error handling' NOT 'Added error handling').\n"
                                    "3. ABSOLUTELY NO full stops (periods) at the end of the subject line or any of the bullet points.\n\n"
                                    "Format EXACTLY like this:\n"
                                    "[extracted_shortcode] type(scope): imperative command subject\\n\\n"
                                    "- imperative description of change 1 without a full stop\\n"
                                    "- imperative description of change 2 without a full stop\\n\\n"
                                    "<Optional: A short paragraph explaining the 'WHY' if the change is complex>\\n\n"
                                    "Ensure <type> is accurately categorized (feat, fix, chore, refactor, docs).\n\n"
                                    "\"summary\": A natural, conversational explanation of the changes. Make it sound like a human wrote it. Escape internal quotes."
                                )
                            },
                            {
                                "role": "user",
                                "content": f"Here is the code change:\n\n{full_diff_text}\n\nPlease provide the JSON response:"
                            }
                        ],
                        temperature=0.2,
                        max_tokens=2048  # Increased to prevent truncated JSON
                    )
                    
                    raw_response = chat_completion.choices[0].message.content
                    
                    if not raw_response or not raw_response.strip():
                        raw_response = '{"lines": "N/A", "commit": "Error: Generation Failed", "summary": "Empty response from AI."}'
                    
                    raw_response = raw_response.strip()
                    
                    # Extract just the JSON block using Regex
                    json_match = re.search(r'\{.*\}', raw_response, re.DOTALL)
                    response_text = json_match.group(0) if json_match else raw_response
                    
                    lines_added_removed = "+0/-0"
                    commit_msg = "No commit message generated."
                    summary_text = "No summary provided."
                    
                    try:
                        # Attempt standard strict JSON parsing
                        data = json.loads(response_text)
                        lines_added_removed = data.get("lines", "+0/-0")
                        commit_msg = data.get("commit", "No commit message generated.")
                        summary_text = data.get("summary", "No summary provided.")
                    except json.JSONDecodeError:
                        print("Standard JSON parsing failed. Falling back to dirty regex extraction.")
                        # DIRTY JSON FALLBACK: Hunt for the keys manually even if the JSON is broken
                        lines_match = re.search(r'"lines"\s*:\s*"(.*?)"', response_text, re.IGNORECASE)
                        if lines_match: 
                            lines_added_removed = lines_match.group(1)
                            
                        commit_match = re.search(r'"commit"\s*:\s*"(.*?)"', response_text, re.IGNORECASE | re.DOTALL)
                        if commit_match: 
                            commit_msg = commit_match.group(1)
                            
                        summary_match = re.search(r'"summary"\s*:\s*"(.*?)"', response_text, re.IGNORECASE | re.DOTALL)
                        if summary_match: 
                            summary_text = summary_match.group(1)
                            
                        # If even the dirty extraction fails completely, dump the raw text
                        if not lines_match and not commit_match and not summary_match:
                            summary_text = f"**Raw AI Output (Failed to parse):**\n{raw_response[:1000]}"

                    # Convert literal '\n' characters back into actual newlines
                    commit_msg = commit_msg.replace('\\n', '\n')

                    # Create the Discord Embed
                    embed = discord.Embed(color=discord.Color.blue())
                    
                    embed.add_field(name="Lines added/removed", value=lines_added_removed, inline=False)
                    embed.add_field(name="Commit message:", value=f"```\n{commit_msg}\n```", inline=False)
                    embed.add_field(name="Summary of changes by User", value=summary_text, inline=False)

                    # Construct header and footer
                    header_text = f"**User:** {mapped_mention}"
                    footer_separator = " " \
                    "------------------------------------------------------------------------------------" \
                    " "

                    # Send
                    await message.channel.send(content=header_text, embed=embed)
                    await message.channel.send(content=footer_separator)

            except Exception as e:
                print(f"An error occurred: {e}")

    await bot.process_commands(message)

if __name__ == "__main__":
    if not DISCORD_TOKEN or not GROQ_API_KEY:
        print("Error: Tokens are missing from environment variables!")
    else:
        bot.run(DISCORD_TOKEN)