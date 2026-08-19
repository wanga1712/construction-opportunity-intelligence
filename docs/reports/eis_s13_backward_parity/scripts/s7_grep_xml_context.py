import subprocess
fname = "/tmp/eis_s13_parity/rgk/contract_2770780719026000028_0_019FACC632FC794F82098EE37699DED9.xml"
result = subprocess.check_output(["grep", "-c", "0373200081226000248", fname], text=True).strip()
print("occurrences:", result)
# Also show the surrounding context
result2 = subprocess.check_output(
    ["grep", "-A", "5", "-B", "5", "0373200081226000248", fname],
    text=True
)
print(result2[:3000])
