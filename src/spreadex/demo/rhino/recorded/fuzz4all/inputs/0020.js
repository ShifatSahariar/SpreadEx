const sym = Symbol("id"), 
      gen = function*(n) {
        let x = 1n;
        while (x <= n) {
          yield x;
          x += 1n;
        }
      },
      vals = [...gen(5n)];

let total = vals.reduce(function(acc, cur) {
  print("Adding", acc, "+", cur, "for symbol", sym.toString());
  return BigInt(acc) + BigInt(cur);
}, 0n);

console.log("Sum as BigInt:", total);

const constTest = 42;   
{
  let constTest = "shadowed"; 
   
  print("Inner let constTest:", constTest);
}
print("Outer const constTest:", constTest);
