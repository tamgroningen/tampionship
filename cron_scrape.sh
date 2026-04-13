#!/bin/bash
# TAMpionship scraper cron job
cd /Users/florisbokx/projects/tam/tampionship
LOG="scrape.log"

export KNLTB_USERNAME="florisbokx"
export KNLTB_PASSWORD="B1nkB1nk!"

echo "--- $(date '+%Y-%m-%d %H:%M:%S') ---" >> "$LOG"
/Users/florisbokx/anaconda3/bin/python3 run_scrape.py >> "$LOG" 2>&1

# Push updated data to GitHub if there are changes
if git diff --quiet knltb_matches.json player_ratings.json rating_history.json 2>/dev/null; then
  echo "No changes to push" >> "$LOG"
else
  git add knltb_matches.json player_ratings.json rating_history.json
  git commit -m "Update match data $(date '+%Y-%m-%d %H:%M')"
  git pull --rebase >> "$LOG" 2>&1
  if git push >> "$LOG" 2>&1; then
    echo "Pushed to GitHub" >> "$LOG"
  else
    echo "Push failed" >> "$LOG"
  fi
fi

echo "" >> "$LOG"
