#!/usr/bin/env bash
set -euo pipefail

SSH_TARGET="${SSH_TARGET:-root@87.226.145.66}"
SSH_PORT="${SSH_PORT:-39001}"
ASTERISK_CONTEXT="${ASTERISK_CONTEXT:-lk-start}"
ASTERISK_EXTENSION="${ASTERISK_EXTENSION:-312388}"
ASTERISK_AFTER_ANSWER_CONTEXT="${ASTERISK_AFTER_ANSWER_CONTEXT:-lk-after-answer}"
AUDIO_FILE="${AUDIO_FILE:-/var/lib/asterisk/sounds/custom/ask_address.wav}"
WAIT_AFTER_ORIGINATE_SEC="${WAIT_AFTER_ORIGINATE_SEC:-70}"
ALLOW_ACTIVE_CALLS="${ALLOW_ACTIVE_CALLS:-0}"

usage() {
  cat <<USAGE
Usage: $0 [--dry-run|--run]

Runs the existing Asterisk LiveKit audio E2E test.

Environment overrides:
  SSH_TARGET=${SSH_TARGET}
  SSH_PORT=${SSH_PORT}
  ASTERISK_CONTEXT=${ASTERISK_CONTEXT}
  ASTERISK_EXTENSION=${ASTERISK_EXTENSION}
  AUDIO_FILE=${AUDIO_FILE}
  WAIT_AFTER_ORIGINATE_SEC=${WAIT_AFTER_ORIGINATE_SEC}
  ALLOW_ACTIVE_CALLS=${ALLOW_ACTIVE_CALLS}
USAGE
}

mode="dry-run"
case "${1:---dry-run}" in
  --dry-run)
    mode="dry-run"
    ;;
  --run)
    mode="run"
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    usage
    exit 2
    ;;
esac

ssh_cmd=(ssh -p "${SSH_PORT}" -o BatchMode=yes "${SSH_TARGET}")
originating_channel="Local/${ASTERISK_EXTENSION}@${ASTERISK_CONTEXT}"
originate_command="channel originate ${originating_channel} application Wait ${WAIT_AFTER_ORIGINATE_SEC}"

echo "Asterisk target: ${SSH_TARGET}:${SSH_PORT}"
echo "Test route: ${originating_channel}"
echo "Audio file: ${AUDIO_FILE}"
echo "Mode: ${mode}"

"${ssh_cmd[@]}" \
  "ASTERISK_EXTENSION='${ASTERISK_EXTENSION}' ASTERISK_CONTEXT='${ASTERISK_CONTEXT}' ASTERISK_AFTER_ANSWER_CONTEXT='${ASTERISK_AFTER_ANSWER_CONTEXT}' AUDIO_FILE='${AUDIO_FILE}' ALLOW_ACTIVE_CALLS='${ALLOW_ACTIVE_CALLS}' bash -s" <<'REMOTE'
set -euo pipefail

echo "--- active channels ---"
channels_line="$(asterisk -rx "core show channels count")"
echo "${channels_line}"
active_calls="$(awk '/active calls/{print $1; exit}' <<<"${channels_line}")"
if [[ "${active_calls}" != "0" && "${ALLOW_ACTIVE_CALLS}" != "1" ]]; then
  echo "Refusing to run while Asterisk has ${active_calls} active calls. Set ALLOW_ACTIVE_CALLS=1 to override." >&2
  exit 3
fi

echo "--- dialplan: ${ASTERISK_EXTENSION}@${ASTERISK_CONTEXT} ---"
asterisk -rx "dialplan show ${ASTERISK_EXTENSION}@${ASTERISK_CONTEXT}"

echo "--- dialplan: s@${ASTERISK_AFTER_ANSWER_CONTEXT} ---"
asterisk -rx "dialplan show s@${ASTERISK_AFTER_ANSWER_CONTEXT}"

echo "--- audio file ---"
test -f "${AUDIO_FILE}"
stat -c "path=%n size=%s bytes mtime=%y" "${AUDIO_FILE}"
file "${AUDIO_FILE}" || true
if command -v ffprobe >/dev/null 2>&1; then
  ffprobe -hide_banner -loglevel error \
    -show_entries format=duration:stream=codec_name,sample_rate,channels \
    -of default=noprint_wrappers=1 \
    "${AUDIO_FILE}" || true
fi
REMOTE

echo "--- originate command ---"
echo "asterisk -rx \"${originate_command}\""

if [[ "${mode}" == "dry-run" ]]; then
  echo "Dry-run complete. Re-run with --run to place one test call."
  exit 0
fi

echo "--- running one test call ---"
"${ssh_cmd[@]}" "asterisk -rx '${originate_command}'"

echo "Waiting ${WAIT_AFTER_ORIGINATE_SEC}s for playback and recordings..."
sleep "${WAIT_AFTER_ORIGINATE_SEC}"

"${ssh_cmd[@]}" 'set -euo pipefail
echo "--- recent test recordings ---"
find /var/spool/asterisk/monitor -maxdepth 1 -type f -name "lk-test-*.wav" -printf "%T@ %p\n" \
  | sort -nr \
  | head -12 \
  | cut -d" " -f2-
echo "--- recent Asterisk log lines ---"
tail -n 80 /var/log/asterisk/messages.log
'
