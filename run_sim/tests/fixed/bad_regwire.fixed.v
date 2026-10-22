// 规则③ reg_to_wire 测试样例：reg 被连续赋值（assign）驱动
// iverilog 报 "cannot be driven by continuous assignments"
module regwire_demo (
    input  wire       clk,
    input  wire [7:0] d,
    output wire  [7:0] q
);
    assign q = d;
endmodule
