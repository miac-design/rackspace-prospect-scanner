#!/usr/bin/env python3
"""
Setup script for weekly healthcare prospect scanning automation on macOS.
Creates a LaunchAgent that runs every Monday at 9:00 AM.
"""

import os
import sys
from pathlib import Path

# Paths
current_dir = Path(__file__).parent.absolute()
venv_python = current_dir / ".venv" / "bin" / "python3"
script_path = current_dir / "prospect_agent.py"
plist_path = Path.home() / "Library" / "LaunchAgents" / "com.rackspace.prospect_scanner.plist"

# Configuration
PLIST_CONTENT = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.rackspace.prospect_scanner</string>
    <key>ProgramArguments</key>
    <array>
        <string>{venv_python}</string>
        <string>{script_path}</string>
        <string>--verbose</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>1</integer> <!-- Monday -->
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>WorkingDirectory</key>
    <string>{current_dir}</string>
    <key>StandardOutPath</key>
    <string>{current_dir}/agent_activity.log</string>
    <key>StandardErrorPath</key>
    <string>{current_dir}/agent_error.log</string>
</dict>
</plist>
"""

def setup():
    if not venv_python.exists():
        print(f"❌ Error: Virtual environment not found at {venv_python}")
        print("Please run 'python3 -m venv .venv && source .venv/bin/activate && pip install feedparser' first.")
        return

    # Create plist
    print(f"📝 Creating LaunchAgent at {plist_path}...")
    with open(plist_path, "w") as f:
        f.write(PLIST_CONTENT)

    # Load the agent
    print("🚀 Loading the automation agent...")
    os.system(f"launchctl unload {plist_path} 2>/dev/null")
    os.system(f"launchctl load {plist_path}")

    print("\n✅ Weekly automation set up successfully!")
    print(f"   The scanner will run every Monday at 9:00 AM.")
    print(f"   Logs will be saved to: {current_dir}/agent_activity.log")

if __name__ == "__main__":
    setup()
