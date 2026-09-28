import os
import yaml
import sys

def load_config():
    """Locates and loads config.yaml for both local CLI and server Bot environments."""
    current_dir = os.path.dirname(os.path.realpath(__file__))
    
    # Path 1: Same directory (used by the installed CLI in ~/.gmd-tool)
    cli_path = os.path.join(current_dir, "config.yaml")
    
    # Path 2: One directory up (used by the bot running in the src/ folder)
    bot_path = os.path.join(current_dir, "..", "config.yaml")
    
    # Determine which path is valid
    if os.path.exists(cli_path):
        config_path = cli_path
    elif os.path.exists(bot_path):
        config_path = bot_path
    else:
        print(f"Error: config.yaml not found in {current_dir} or parent directory.")
        sys.exit(1)
        
    try:
        with open(config_path, "r") as file:
            return yaml.safe_load(file)
    except Exception as e:
        print(f"Error reading config.yaml: {e}")
        sys.exit(1)