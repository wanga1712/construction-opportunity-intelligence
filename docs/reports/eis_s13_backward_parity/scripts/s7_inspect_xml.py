import subprocess, os

contract = "0373200081226000248"
xml_dir = "/tmp/eis_s13_parity/rgk"
out = subprocess.check_output(["find", xml_dir, "-maxdepth", "1", "-name", f"*{contract}*"], text=True).strip()
print("Files:", out)
if out:
    fname = out.split("\n")[0]
    result = subprocess.check_output(["grep", "-o", "price>[^<]*</price", fname], text=True)
    print("price tags:", result)
    result2 = subprocess.check_output(["grep", "-o", "contractPrice>[^<]*</contractPrice", fname], text=True)
    print("contractPrice tags:", result2)
