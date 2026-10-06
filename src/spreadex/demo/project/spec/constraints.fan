import re

# A division by a literal zero is already known to be rejected by MiniCalc:
# do not spend budget on it. The remainder operator (%) is deliberately left alone.
where all(float(d) != 0 for d in re.findall(r" / -*([0-9]+(?:\.[0-9]+)?)", str(<start>)))
