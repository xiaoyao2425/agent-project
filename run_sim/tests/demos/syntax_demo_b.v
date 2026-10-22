// syntax_demo_b.v
// 注意：文件名与模块名(counter)不一致（案例010 DECLFILENAME 警告的演示素材）
// 本文件同时包含案例008（ens 未声明信号）与案例010（文件名不匹配）
`timescale 1ns/1ps

module counter #(
    parameter WIDTH = 4
)(
    input  wire              clk,
    input  wire              rst_n,
    input  wire              en,
    output reg  [WIDTH-1:0]  q
);

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        q <= {WIDTH{1'b0}};
    end
    else if (en) begin
        q <= q + 1'b1;
    end
    else if (ens)
        q <= q;
end

endmodule
