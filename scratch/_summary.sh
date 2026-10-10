#!/bin/bash
# usage: bash /tmp/_summary.sh <file> [pattern]
PATTERN="${2:-SUMMARY|^direct=|^progress}"
grep -E "$PATTERN" "$1"
