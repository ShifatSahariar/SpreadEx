var x = 1, y = 2;   
function* gen() {
  yield BigInt(x + y);        
  let sym = Symbol("id");     
  {
    let sym = Symbol("nested");  
    yield sym;
  }
  yield sym;                  
}
const c = "const";  

print("c before block:", c);
{
  const c = 42;   
  print("c inside block:", c);
}
print("c after block:", c);

var it = gen();
print("BigInt sum:", it.next().value.toString());
console.log("Nested symbol:", it.next().value.toString());
console.log("Outer symbol:", it.next().value.toString());

try {
  let a = 1; let a = 2;  
} catch (e) {
  print("Caught syntax error as expected");
}
