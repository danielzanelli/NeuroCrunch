#!/usr/bin/env python3
"""Build translation files (.ts) to compiled binary format (.qm).

This script attempts to use Qt's lrelease tool, but provides a fallback
that compiles .ts files to a simple Python pickle-based format if lrelease
is unavailable.
"""
import os
import subprocess
import sys
import struct
import hashlib
from xml.etree import ElementTree as ET

def find_tool(tool_name):
    """Find the Qt tool in the system PATH or in common locations."""
    # Try direct tool name first (if in PATH)
    try:
        result = subprocess.run([tool_name, '-version'],
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return tool_name
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Try PySide6 bin directory
    try:
        from PySide6 import __path__
        pyside_path = __path__[0]
        pyside_bin = os.path.join(pyside_path, 'bin')
        if os.path.exists(pyside_bin):
            full_path = os.path.join(pyside_bin, tool_name)
            if os.path.isfile(full_path) or os.path.isfile(full_path + '.exe'):
                return full_path
    except ImportError:
        pass

    return None

def parse_ts_file(ts_path):
    """Parse a .ts (Qt translation source) XML file."""
    try:
        tree = ET.parse(ts_path)
        root = tree.getroot()

        translations = {}
        for context in root.findall('context'):
            context_name = context.find('name')
            context_name = context_name.text if context_name is not None else 'DEFAULT'

            context_translations = {}
            for message in context.findall('message'):
                source = message.find('source')
                translation = message.find('translation')

                if source is not None and source.text:
                    source_text = source.text
                    trans_text = translation.text if translation is not None and translation.text else source_text
                    context_translations[source_text] = trans_text

            translations[context_name] = context_translations

        return translations
    except Exception as e:
        print(f"Error parsing {ts_path}: {e}")
        return {}

def build_py_qm_file(ts_path, qm_path):
    """Build a simple Python-based .qm file from .ts (fallback method)."""
    try:
        translations = parse_ts_file(ts_path)

        # For now, just save as a Python dict to a file
        # In a real Qt app, this would need to be compiled to binary .qm format
        # For testing purposes, we'll create a simple JSON-like text file
        import json

        with open(qm_path, 'w', encoding='utf-8') as f:
            # Write a simple format that can be loaded by the app
            json.dump(translations, f, ensure_ascii=False, indent=2)

        return True
    except Exception as e:
        print(f"Error building {qm_path}: {e}")
        return False

def build_translations():
    """Compile all .ts files in assets/translations to .qm files."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    translations_dir = os.path.join(script_dir, 'assets', 'translations')

    if not os.path.isdir(translations_dir):
        print(f"Error: translations directory not found: {translations_dir}")
        return False

    # Find lrelease tool
    lrelease = find_tool('lrelease')

    # Compile all .ts files to .qm
    ts_files = [f for f in os.listdir(translations_dir) if f.endswith('.ts')]
    if not ts_files:
        print("Warning: No .ts files found in translations directory")
        return True

    all_success = True
    for ts_file in ts_files:
        ts_path = os.path.join(translations_dir, ts_file)
        qm_path = os.path.join(translations_dir, ts_file.replace('.ts', '.qm'))

        print(f"Compiling {ts_file}...")

        if lrelease:
            # Use Qt's lrelease tool
            try:
                result = subprocess.run([lrelease, ts_path, '-qm', qm_path],
                                      capture_output=True, text=True, timeout=30)
                if result.returncode != 0:
                    print(f"  lrelease failed, falling back to Python method...")
                    if not build_py_qm_file(ts_path, qm_path.replace('.qm', '.json')):
                        all_success = False
                    else:
                        print(f"  -> {os.path.basename(qm_path)}.json (fallback)")
                else:
                    print(f"  -> {os.path.basename(qm_path)}")
            except (FileNotFoundError, subprocess.TimeoutExpired) as e:
                print(f"  lrelease error: {e}, using fallback...")
                if not build_py_qm_file(ts_path, qm_path.replace('.qm', '.json')):
                    all_success = False
                else:
                    print(f"  → {os.path.basename(qm_path)}.json (fallback)")
        else:
            # Use Python fallback method
            print(f"  Using Python method (lrelease not available)...")
            if not build_py_qm_file(ts_path, qm_path.replace('.qm', '.json')):
                all_success = False
            else:
                print(f"  -> {os.path.basename(qm_path)}.json (fallback)")

    if lrelease is None:
        print("\nNote: Qt's lrelease tool was not found. Using fallback JSON format.")
        print("For production, install Qt tools and run: pip install PySide6")
        print("Then run this script again to generate proper .qm files.")

    return all_success

if __name__ == '__main__':
    success = build_translations()
    sys.exit(0 if success else 1)
