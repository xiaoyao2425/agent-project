// case05：语义错误（使用未声明信号）——规则修复器应明确拒绝（fail/unsupported），
// 而不是乱修一通。测的是"边界清晰性"：不能修的要认得出来。
module semantic_demo (
    input  wire       clk,
    input  wire [7:0] d,
    output reg  [7:0] q
);
    always @(posedge clk) begin
        q <= d + undeclared_sig;  // BUG: undeclared_sig 从未声明
    end
endmodule
