console.log("Start");

 
console.log("var x before init:", x);  
var x = 10;

{
  let y = 20;          
  const x = 999;       
   
  console.log("Inside block let y:", y);  
  console.log("Inside block const x (which is global):", x);  
}
console.log("After block, global x:", x);  

 
 
 

 
var big = 100n;
var big2 = 200n;
var sumBig = big + big2;
console.log("BigInt sum:", sumBig.toString());

 
try {
  var mix = big + 5;  
} catch (e) {
  console.log("Mix BigInt and Number error:", e);
}

 
{
  hoisted();
  function hoisted() {
    console.log("Hoisted function called inside block");
  }
}

 
function* gen() {
  yield 42;
  yield "hello";
  yield Symbol("sym");
  yield null;
  yield undefined;
  yield 5n;
}
var g = gen();
for (var v of g) {
  console.log("Yielded:", v, "type:", typeof v);
}

 
try {
  throw "string error";
} catch (e) {
  console.log("Caught error:", e);
}
try {
  throw 12345;
} catch (e) {
  console.log("Caught number error:", e);
}
try {
  throw { msg: "object error" };
} catch (e) {
  console.log("Caught object error msg:", e.msg);
}

console.log("End");
