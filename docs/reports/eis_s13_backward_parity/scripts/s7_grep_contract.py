import subprocess
contract = "0373200081226000248"
result = subprocess.check_output(
    ["grep", "-rl", contract, "/tmp/eis_s13_parity/rgk"],
    text=True
)
print("Files referencing contract:", result)
