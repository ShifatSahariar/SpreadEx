print("Start");

 
print(foo());  

 
print(x); 
var x = 10;

 
{
  let y = 5;
  print(y);
   
   
}
const c = "const?";
print(c);

 
var sym = Symbol("key");
var obj = {};
obj[sym] = "symbolic";
print(obj[sym]);

 
var bi = 10n;
var n = 5;
print(bi + 5n);        
 
print(Number(bi) + n);  

 
function* gen() {
  yield 1;
  var [a, b = 2, ...rest] = [yield, yield * 2];
  yield a + b + rest.length;
}

var g = gen();
print(g.next().value);         
print(g.next(10).value);       
print(g.next(3).value);        

 
var {p: q = x, p, r = 42} = {p: undefined};
print(q, p, r);  
 
const s = "const";
print(s);

print("End");
