#!/bin/bash
# The full run (plan Task 14, steps 2-4), detached from the terminal so it survives
# closing it: settle the base sheets, then the variants, then verify. Each phase
# alternates ComfyUI batch passes with vLLM reviews, swapping the two services
# itself (they do not fit in memory together), until a review rejects nothing.
#
#   ./full_run.sh start    start, or resume after a stop, a crash or a reboot
#   ./full_run.sh stop     Ctrl-C the run (the current sheet is abandoned cleanly)
#   ./full_run.sh status   where it is, and the sheet counts so far
#   ./full_run.sh log      follow the run log
#
# Everything resumes from the audit folders: a restart re-renders nothing done.
# A settled phase leaves data/run/<phase>.settled, so a restart skips it; delete
# the marker to run that phase again. Logs: data/run/{run,batch,review,stuck}.log.
# STUCK sheets are only listed (stuck.log): fix their captions, then
# make batch sheet=<key> force=1, and start again.
set -u
cd "$(dirname "$0")"
RUN=data/run
PIDFILE=$RUN/driver.pid
ROUNDS=${ROUNDS:-6}         # batch-and-review rounds per phase before moving on

running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }
log() { echo "$(date '+%F %T') $*" >> "$RUN/run.log"; }
comfy_up() { curl -s -m 3 localhost:8188/system_stats >/dev/null; }
vllm_up() { curl -s -m 3 localhost:8000/v1/models | grep -q Qwen; }

start_comfy() {
    docker stop vllm-server lmcache-server >/dev/null 2>&1
    if ! comfy_up; then
        ./run_server.sh >> "$RUN/comfy.log" 2>&1 &
        until comfy_up; do sleep 5; done
    fi
    log "ComfyUI up"
}

stop_comfy() {
    curl -s -X POST localhost:8188/free -H 'Content-Type: application/json' \
         -d '{"unload_models":true,"free_memory":true}' >/dev/null
    pkill -f "python main.py --listen 0.0.0.0 --port 8188"
    while comfy_up; do sleep 2; done
}

start_vllm() {
    stop_comfy
    docker start lmcache-server vllm-server >/dev/null
    until vllm_up; do sleep 10; done
    log "vLLM up"
}

settle() {  # phase name, then make arguments
    local phase=$1; shift
    if [ -f "$RUN/$phase.settled" ]; then log "=== $phase already settled"; return; fi
    log "=== $phase: up to $ROUNDS rounds"
    local round pass out summary
    for round in $(seq 1 "$ROUNDS"); do
        start_comfy
        for pass in $(seq 1 10); do
            log "$phase round $round batch pass $pass"
            out=$(make batch "$@" 2>&1)
            echo "$out" | grep -v '^\./run_batch' >> "$RUN/batch.log"
            echo "$out" | grep STUCK >> "$RUN/stuck.log"
            summary=$(echo "$out" | grep '^done:')
            [ -n "$summary" ] || { log "batch gave no summary - see $RUN/batch.log; stopping"; exit 1; }
            log "  $summary"
            echo "$summary" | grep -qE 'promoted=0 rejected=0 failed=0' && break
        done
        start_vllm
        log "$phase round $round review"
        out=$(make review "$@" 2>&1)
        echo "$out" | grep -v '^\./run_batch' >> "$RUN/review.log"
        summary=$(echo "$out" | grep '^done:')
        [ -n "$summary" ] || { log "review gave no summary - see $RUN/review.log; stopping"; exit 1; }
        log "  $summary"
        if echo "$summary" | grep -q ' rejected=0 '; then
            touch "$RUN/$phase.settled"
            log "=== $phase settled after round $round"
            return
        fi
    done
    log "=== $phase: $ROUNDS rounds without settling; moving on (start again for more rounds)"
}

drive() {
    echo $$ > "$PIDFILE"        # the session leader: stop signals its whole group
    trap 'log "stopped"; stop_comfy; rm -f "$PIDFILE"; exit 130' INT TERM
    log "driver started (pid $$)"
    settle bases variants=0
    settle variants
    log "=== verify"
    make verify >> "$RUN/verify.log" 2>&1
    log "  $(tail -1 "$RUN/verify.log")"
    log "=== full run finished"
    rm -f "$PIDFILE"
}

case ${1:-} in
    start)
        mkdir -p "$RUN"
        if running; then echo "already running (pid $(cat "$PIDFILE"))"; exit 1; fi
        # setsid -f, not `&`: a script's background job would ignore Ctrl-C for good,
        # and stop could not reach the batch.
        rm -f "$PIDFILE"
        setsid -f nohup "$0" _drive > "$RUN/driver.out" 2>&1 < /dev/null
        for _ in 1 2 3 4 5 6 7 8 9 10; do running && break; sleep 0.5; done
        running || { echo "did not start - see $RUN/driver.out"; exit 1; }
        echo "started (pid $(cat "$PIDFILE")); ./full_run.sh status or ./full_run.sh log to watch"
        ;;
    stop)
        if ! running; then echo "not running"; exit 0; fi
        kill -INT -- "-$(cat "$PIDFILE")"      # the whole session: batch, make, ComfyUI
        echo "stopping (the current sheet is abandoned; start resumes)"
        ;;
    status)
        if running; then echo "running (pid $(cat "$PIDFILE"))"; else echo "not running"; fi
        tail -n 5 "$RUN/run.log" 2>/dev/null
        attempts=$(find data/anims-ai/.quality -name 'attempt-*.json' 2>/dev/null | wc -l)
        promoted=$(find data/anims-ai/.quality -name 'attempt-*.json' -exec grep -l '"promoted": true' {} + 2>/dev/null | wc -l)
        stuck=$(sort -u "$RUN/stuck.log" 2>/dev/null | wc -l)
        echo "attempts: $attempts  promoted: $promoted  stuck lines: $stuck"
        ;;
    log) tail -F "$RUN/run.log" ;;
    _drive) drive ;;
    *) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
