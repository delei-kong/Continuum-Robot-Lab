#!/usr/bin/env bash

# Codex 生命周期事件的本地声音提示。
# 用法：ring.sh stop | notification

set -u

event_name="${1:-notification}"

play_sound() {
    local requested_event="$1"

    if [[ "${CONTINUUM_BELL_DRY_RUN:-0}" == "1" ]]; then
        return 0
    fi

    case "$(uname -s)" in
        Darwin)
            local sound_file
            case "$requested_event" in
                stop) sound_file="/System/Library/Sounds/Ping.aiff" ;;
                notification) sound_file="/System/Library/Sounds/Ping.aiff" ;;
            esac
            if command -v afplay >/dev/null 2>&1 && [[ -r "$sound_file" ]]; then
                afplay "$sound_file" >/dev/null 2>&1
                return 0
            fi
            if command -v osascript >/dev/null 2>&1; then
                osascript -e 'beep 2' >/dev/null 2>&1
                return 0
            fi
            ;;
        Linux)
            if command -v canberra-gtk-play >/dev/null 2>&1; then
                canberra-gtk-play --id=complete >/dev/null 2>&1
                return 0
            fi
            if command -v paplay >/dev/null 2>&1; then
                local sound_file="/usr/share/sounds/freedesktop/stereo/complete.oga"
                if [[ -r "$sound_file" ]]; then
                    paplay "$sound_file" >/dev/null 2>&1
                    return 0
                fi
            fi
            ;;
    esac

    # 最后尝试向当前终端发送 ASCII Bell；无终端时保持静默成功。
    (printf '\a' >/dev/tty) 2>/dev/null || true
}

case "$event_name" in
    stop|notification)
        play_sound "$event_name"
        ;;
    *)
        printf 'Usage: %s {stop|notification}\n' "$0" >&2
        exit 64
        ;;
esac

# Stop hook 成功时必须向 Codex 返回合法 JSON；PermissionRequest 会忽略空 stdout。
if [[ "$event_name" == "stop" ]]; then
    printf '{"continue":true}\n'
fi
