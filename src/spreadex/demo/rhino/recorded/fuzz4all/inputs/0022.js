function* factorials(n) {
  var i = 1n, f = 1n;
  while(i <= n) {
    f *= i;
    yield f;
    i++;
  }
}

let limit = 10n;   
for (const f of factorials(limit)) {
  print(String(f));   
}
