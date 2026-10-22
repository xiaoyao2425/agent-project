// timeout_demo.v —— 案例009 的 DUT
// BUG：ready 被强制恒为 0，valid/ready 握手永远无法完成
`timescale 1ns/1ps
module timeout_demo (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       valid,
    output reg        ready,
    output reg  [7:0] data_out
);

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        ready    <= 1'b0;
        data_out <= 8'd0;
    end else begin
        ready    <= 1'b0;   // 故障点：正常逻辑应在空闲时 ready <= 1'b1
        data_out <= data_out;
    end
end

endmodule
