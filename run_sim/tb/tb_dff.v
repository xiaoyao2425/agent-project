`timescale 1ns/1ps
module tb_dff;
    reg clk, d, rst_n;
    wire q;
    dff u_dff (.clk(clk), .d(d), .rst_n(rst_n), .q(q));
    initial begin
        $dumpfile("waves/dff.vcd");
        $dumpvars(0, tb_dff);
    end
    initial begin
        clk = 0;
        forever #5 clk = ~clk;
    end
    initial begin
        rst_n = 0; d = 0; #10;
        rst_n = 1; #10;
        d = 1; #10;
        d = 0; #10;
        d = 1; #10;
        $finish;
    end
endmodule
