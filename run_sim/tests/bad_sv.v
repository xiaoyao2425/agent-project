// 规则② sv_to_2001 测试样例：SystemVerilog 构造混入 Verilog-2001
// iverilog 只会报笼统 syntax error，规则直接扫源码转换
module sv_demo (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] d,
    output reg  [7:0] q
);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            q <= 8'h0;
        else
            q <= d;
    end
endmodule
