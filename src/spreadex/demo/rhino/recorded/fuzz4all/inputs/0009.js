print(
  (function* gen(n) {
    var x = 10, y;
    let z = 0;
    const c = "const?";  
    try { let z = 1; let z = 2; } catch(e) { y = e.name || e + "" }  
    while (z < n) {
      z++;
      yield (typeof Symbol === "function" && Symbol.iterator) || "noSymbol";
    }
    return y + "-" + c;
  })(3)
  .next().value 
  + " " + (() => (true && false || "fallback"))()   
  + " " + (42n + 58n)  
  + " " + (1 + "1")    
);
