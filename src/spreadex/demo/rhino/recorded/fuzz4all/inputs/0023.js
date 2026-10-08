var x = 1;
{
    let x = "shadow";  
    const x = 42n;     
                       
     

     
    print("Inner x before var x2:", x);  

    var x2;
    print("x2 after var declaration:", x2);
    x2 = () => 10;

     
    let sym = Symbol("s");
    let obj = {
        [sym]: function* (n) {
             
            for (let i = 0n; i < n; i += 1n) yield i * i;
        }
    };

    try {
        throw { error: "custom", value: x };
    } catch(e) {
        print("Caught:", e.error, "with value type:", typeof e.value, "value:", e.value.toString());
    }

    let gen = obj[sym](5n);
    let seq = [];
    for (let res = gen.next(); !res.done; res = gen.next()) {
        seq.push(res.value.toString());
    }
    print("Squares (BigInt):", seq.join(","));

    print("x2() returns:", x2());

     
    print("y before let y:", typeof y);
    let y = "initialized";

     
    print("y after init:", y);
}

print("Outer x after block:", x);

 
print("z before var declaration:", typeof z);
var z = 7;
print("z after init:", z);

 
let sym2 = Symbol("foo");
print("Symbol to string via coercion:", sym2.toString
