// assert_pass 功能自检的失败场景样例：DUT 正常，但 tb 断言条件写反，
// 仿真跑完打印 FAIL —— vvp 退出码为 0，只有 assert_pass 判定能抓住
module fail_demo (
    input  wire clk,
    input  wire rst_n,
    output reg  o
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            o <= 1'b0;
        else
            o <= ~o;
    end
endmodule

module tb_fail_demo;
    reg clk = 0;
    reg rst_n = 0;
    wire o;
    integer i;

    fail_demo u0 (.clk(clk), .rst_n(rst_n), .o(o));

    always #5 clk = ~clk;

    initial begin
        $dumpfile("waves/tb_fail_demo.vcd");
        $dumpvars(0, tb_fail_demo);
        #20 rst_n = 1;
        for (i = 0; i < 10; i = i + 1) @(posedge clk);
        if (o === 1'b0) $display("PASS");
        else            $display("FAIL: expect o==0 but got %b", o);
        $finish;
    end
endmodule
