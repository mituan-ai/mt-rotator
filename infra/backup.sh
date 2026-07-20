#!/bin/sh
set -eu

exec "$(dirname "$0")/../ops/mt-rotator" backup
