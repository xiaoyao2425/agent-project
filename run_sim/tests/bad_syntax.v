// 案例②专用：故意制造语法错误 —— 第 7 行 assign 末尾少了分号
module bad_syntax(
    input  wire a,
    input  wire b,
    output wire y
);
    assign y = a & b
endmodule
