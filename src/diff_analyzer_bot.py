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

        # Only proceed if there is actual text to process
        if extracted_text:
            try:
                # Capture timestamp
                time_ran = datetime.now().strftime("%H:%M")
                
                # Determine user mention
                mapped_mention = message.author.mention
                for shortcode, discord_username in DISCORD_USER_MAPPINGS.items():
                    if shortcode in extracted_text:
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

                print(f"--- Processing new diff ---\nExtracted {len(extracted_text)} characters.")

                async with message.channel.typing():
                    # Call API with higher max_tokens to prevent cut-offs
                    chat_completion = await groq_client.chat.completions.create(
                        model="openai/gpt-oss-20b",
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    "You are an expert developer assistant. Analyze the provided git diff and output a JSON object. "
                                    "The JSON object must contain exactly these three keys:\n"
                                    "\"lines\": The lines added and removed (e.g., '+15/-3').\n"
                                    "\"commit\": The commit message. Escape any quotes inside this string.\n"
                                    "\"summary\": A concise explanation of the changes. Escape any quotes."
                                )
                            },
                            {
                                "role": "user",
                                "content": f"Here is the code change:\n\n{extracted_text}\n\nPlease provide the JSON response:"
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

                    # Create the Discord Embed
                    embed = discord.Embed(color=discord.Color.blue())
                    
                    embed.add_field(name="Lines added/removed", value=lines_added_removed, inline=False)
                    embed.add_field(name="Commit message:", value=f"```\n{commit_msg}\n```", inline=False)
                    embed.add_field(name="Summary of changes by User", value=summary_text, inline=False)

                    # Construct header and footer
                    header_text = f"**User:** {mapped_mention}"
                    footer_separator = "------------------------------------------------------------------------------------"

                    # Send
                    await message.channel.send(content=header_text, embed=embed)
                    await message.channel.send(content=footer_separator)

                # Delete the original message containing the diff
                await message.delete()

            except discord.Forbidden:
                print("Error: Bot lacks 'Manage Messages' permission to delete messages.")
            except Exception as e:
                print(f"An error occurred: {e}")

    await bot.process_commands(message)

if __name__ == "__main__":
    if not DISCORD_TOKEN or not GROQ_API_KEY:
        print("Error: Tokens are missing from environment variables!")
    else:
        bot.run(DISCORD_TOKEN)