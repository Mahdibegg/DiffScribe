#!/bin/bash

# Define names
PYTHON_FILE="src/diff_cli.py"
LOADER_FILE="src/config_loader.py"
CONFIG_FILE="config.yaml"
COMMAND_NAME="gmd"

APP_DIR="$HOME/.gmd-tool"
BIN_DIR="$HOME/.local/bin"

echo "Installing $COMMAND_NAME..."

# Check if config.yaml exists before installing
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: config.yaml is missing. Please copy config.example.yaml to config.yaml and fill it out."
    exit 1
fi

mkdir -p "$APP_DIR"
mkdir -p "$BIN_DIR"

# Copy the scripts and the configuration file to the hidden directory
cp "$PYTHON_FILE" "$APP_DIR/main.py"
cp "$LOADER_FILE" "$APP_DIR/config_loader.py"
cp "$CONFIG_FILE" "$APP_DIR/config.yaml"

# Create the executable bash wrapper
cat << EOF > "$BIN_DIR/$COMMAND_NAME"
#!/bin/bash
python3 "$APP_DIR/main.py" "\$@"
EOF

chmod +x "$BIN_DIR/$COMMAND_NAME"

echo "Installation complete! Type '$COMMAND_NAME' in any git repository."