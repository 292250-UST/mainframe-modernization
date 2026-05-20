import subprocess, json

base = "http://localhost:8000"
tests = [
    ("/health",                          "status"),
    ("/coverage",                        "pass_rate"),
    ("/program/COTRN02C",               "paragraph_count"),
    ("/paragraph/994395d163f4caca58c1703e6c4188ec", "statements"),
    ("/retrieve/875123c70d767e89c93dd62673ba4b01",  "kind"),
    ("/callees/COTRN02C",               "count"),
    ("/callers/CBSTM03B",               "count"),
    ("/fileaccesses/CBACT01C",          "count"),
    ("/transactionflow/CA00",           "count"),
    ("/jobchain/POSTTRAN",              "known_chains"),
    ("/copybookconsumers/CVACT01Y",     "count"),
    ("/businessrules/COCRDLIC",         "count"),
    ("/controlflow/COTRN02C",           "count"),
    ("/defuse/COTRN02C",               "total_vars"),
    ("/connectivity/CBSTM03A",         "connectivity_summary"),
]

print(f"{'Endpoint':<45} {'Key':<20} {'Value'}")
print("-" * 80)
for endpoint, key in tests:
    try:
        result = subprocess.run(
            ["curl.exe", "-s", base + endpoint],
            capture_output=True, text=True, timeout=10
        )
        data = json.loads(result.stdout)
        val  = data.get(key, "NOT FOUND")
        if isinstance(val, dict):
            val = str(val)[:40]
        elif isinstance(val, list):
            val = f"[{len(val)} items]"
        status = "✅" if val != "NOT FOUND" else "❌"
        print(f"{status} {endpoint:<43} {key:<20} {val}")
    except Exception as e:
        print(f"❌ {endpoint:<43} ERROR: {str(e)[:30]}")
