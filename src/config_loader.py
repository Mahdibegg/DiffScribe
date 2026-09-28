import os
import yaml
import sys

def load_config():
    """Loads the config.yaml file located one directory above the current script."""
    # Get the directory where this script (src/) is located
    current_dir = os.path.dirname(os.path.realpath(__file__))
    # Go up one level to find config.yaml
    config_path = os.path.join(current_dir, "..", "config.yaml")
    
    try:
        with open(config_path, "r") as file:
            return yaml.safe_load(file)
    except FileNotFoundError:
        print(f"Error: config.yaml not found at {config_path}")
        sys.exit(1)