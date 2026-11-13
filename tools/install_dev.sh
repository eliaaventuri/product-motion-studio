#!/bin/bash
# Installs Product Motion Studio for development: symlinks plugin/product_motion_studio into Blender's
# user extensions repository and enables it. Idempotent (run it as many times as you like).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="$ROOT/plugin/product_motion_studio"
BLENDER="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
DEST_DIR="${PMS_EXT_DIR:-$HOME/Library/Application Support/Blender/5.1/extensions/user_default}"

mkdir -p "$DEST_DIR"
ln -sfn "$SRC" "$DEST_DIR/product_motion_studio"      # -n: replace an existing link instead of nesting inside it
echo "link: $DEST_DIR/product_motion_studio -> $SRC"

"$BLENDER" -b --python-expr "
import bpy
bpy.ops.preferences.addon_enable(module='bl_ext.user_default.product_motion_studio')
bpy.ops.wm.save_userpref()
print('PMS enabled:', 'bl_ext.user_default.product_motion_studio' in bpy.context.preferences.addons)
" 2>&1 | grep -a -E "PMS enabled|Error|Traceback" || true
echo "done: open Blender, N panel > PMS"
