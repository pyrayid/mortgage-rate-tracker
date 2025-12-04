import subprocess
import sys

try:
    result = subprocess.run(
        [sys.executable, "create_bank_config.py", "https://www.robinsfcu.org/mortgage-loans#mortgage-rates", "--json"],
        capture_output=True,
        text=True
    )
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
    with open("error_log.txt", "w") as f:
        f.write(result.stderr)
except Exception as e:
    print(e)
