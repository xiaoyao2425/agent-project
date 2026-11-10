// syntax_demo_a.v —— 案例007：连续赋值语句末尾漏写分号
`timescale 1ns/1ps
module syntax_demo_a #(
    parameter WIDTH = 4
)(
    input  wire              clk,
    input  wire              rst_n,
    input  wire              en,
    input  wire [WIDTH-1:0]  din,
    output reg  [WIDTH-1:0]  cnt_reg,
    output wire [WIDTH-1:0]  cnt_val
);

// 计数器寄存器
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        cnt_reg <= {WIDTH{1'b0}};
    end else if (en) begin
        cnt_reg <= cnt_reg + din;
    end
end

// 计数结果引出
// BUG: 下一行 assign 语句末尾故意漏掉分号
// iverilog 在本行(26)报错，Verilator 会延迟到下一行(27)报错
assign cnt_val = cnt_reg;

endmodule
