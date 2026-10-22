// tb_timeout_demo.v —— 案例009：valid/ready 握手超时
`timescale 1ns/1ps
module timeout_demo_tb;

    reg        clk;
    reg        rst_n;
    reg        valid;
    wire       ready;
    wire [7:0] data_out;

    // 例化 DUT：其内部 ready 恒为 0，握手永远无法完成
    timeout_demo u_dut (
        .clk      (clk),
        .rst_n    (rst_n),
        .valid    (valid),
        .ready    (ready),
        .data_out (data_out)
    );

    always #5 clk = ~clk;   // 100MHz 时钟

    initial begin
        $dumpfile("timeout_demo.vcd");
        $dumpvars(0, timeout_demo_tb);
        clk   = 1'b0;
        rst_n = 1'b0;
        valid = 1'b0;
        #20 rst_n = 1'b1;
        #10 valid = 1'b1;
    end

    // 握手状态监视（每个时间步打印信号值）
    initial begin
        $monitor("time=%0t valid=%b ready=%b data_out=%h",
                 $time, valid, ready, data_out);
    end

    // 仿真看门狗
    initial begin
        // 10000ns 内握手未完成则报 FATAL
        #10000; if (!(valid && ready)) $display("FATAL: TIMEOUT - valid && ready handshake never completed within 10000 ns (module timeout_demo_tb, line 41)");
        $finish;
    end

endmodule
