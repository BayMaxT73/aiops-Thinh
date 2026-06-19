import json
from chaos_runner import print_scoreboard

with open("chaos_results.json", "r") as f:
    results = json.load(f)

print_scoreboard(results)
