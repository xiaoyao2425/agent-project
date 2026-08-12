`timescale 1ns/1ps
module tb_counter;
    reg clk, rst_n;
    wire [3:0] count;
    counter u_counter (.clk(clk), .rst_n(rst_n), .count(count));
    initial begin
        $dumpfile("waves/counter.vcd");
        $dumpvars(0, tb_counter);
    end
    initial begin
        clk = 0;
        forever #5 clk = ~clk;
    end
    initial begin
        rst_n = 0; #10;
        rst_n = 1; #50;
        rst_n = 0; #20;
        rst_n = 1; #50;
        $finish;
    end
endmodule
