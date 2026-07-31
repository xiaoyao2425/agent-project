cat > mux.v << 'EOF'
module mux2x1 (
    input a, b, sel,
    output reg y
);
    always @(*) begin
        if (sel) y = b;
        else y = a;
    end
endmodule
EOF
