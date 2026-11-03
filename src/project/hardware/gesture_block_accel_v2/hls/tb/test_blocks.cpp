#include "blocks56_axis.h"
#include <cmath>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

static std::vector<float> read(const std::string& file,int count) {
    std::vector<float> value(count); std::ifstream in(file,std::ios::binary);
    in.read(reinterpret_cast<char*>(value.data()),count*4);
    if(!in || in.peek()!=std::ifstream::traits_type::eof()) throw std::runtime_error("Bad vector: "+file);
    return value;
}
static void push(hls::stream<block_axis_word>& s,unsigned bits,bool last) {
    block_axis_word w; w.data=bits; w.keep=0xF; w.strb=0xF; w.last=last; s.write(w);
}
static void command(hls::stream<block_axis_word>& s,unsigned op,unsigned bank,const std::vector<float>& payload={}) {
    push(s,BLOCK_MAGIC,false); push(s,op,false); push(s,bank,false); push(s,BLOCK_VERSION,payload.empty());
    for(size_t i=0;i<payload.size();i++) push(s,block_bits(payload[i]).to_uint(),i+1==payload.size());
}
static unsigned ack(hls::stream<block_axis_word>& s) {
    auto w=s.read(); if(w.keep!=15 || w.strb!=15 || !w.last || !s.empty()) throw std::runtime_error("Bad status packet");
    return w.data.to_uint();
}
static void check(hls::stream<block_axis_word>& out,const std::vector<float>& expected) {
    double max_error=0; int failed=0;
    for(int i=0;i<BLOCK_FRAME_WORDS;i++) {
        if(out.empty()) throw std::runtime_error("Short hardware output");
        auto w=out.read(); float actual=block_float(w.data);
        if(w.keep!=15 || w.strb!=15 || bool(w.last)!=(i==BLOCK_FRAME_WORDS-1)) throw std::runtime_error("AXIS sideband mismatch");
        double error=std::fabs(double(actual)-expected[i]); max_error=std::fmax(max_error,error);
        if(!std::isfinite(actual) || error>1e-4+1e-4*std::fabs(expected[i])) {
            if(failed<4) std::cerr<<"Mismatch "<<i<<" got "<<actual<<" expected "<<expected[i]<<"\n";
            failed++;
        }
    }
    if(!out.empty() || failed) throw std::runtime_error("Numeric/length failure; failed="+std::to_string(failed)+" max="+std::to_string(max_error));
    std::cout<<"PASS tensor words="<<expected.size()<<" max_abs="<<max_error<<std::endl;
}

int main(int argc,char** argv) {
    try {
        if(argc!=2) throw std::runtime_error("Expected project root argument");
        std::string root=argv[1]; hls::stream<block_axis_word> in,out;
        command(in,BLOCK_PING,0); gesture_blocks56_axis(in,out);
        if(ack(out)!=0xA5010000 || !in.empty()) throw std::runtime_error("Cold signature failed");
        command(in,BLOCK_RUN,0); gesture_blocks56_axis(in,out);
        if(ack(out)!=0xE1000002) throw std::runtime_error("Cold RUN was accepted");
        std::vector<float> params[2];
        for(int bank=0;bank<2;bank++) {
            params[bank]=read(root+"/export/params/block"+std::to_string(bank)+".bin",BLOCK_PARAM_WORDS);
            command(in,BLOCK_LOAD,bank,params[bank]); gesture_blocks56_axis(in,out);
            unsigned flags=bank==0?1:3;
            if(ack(out)!=(0xA5010000|(flags<<8)|bank) || !in.empty()) throw std::runtime_error("Parameter load failed");
        }
        std::ifstream list(root+"/export/case_list.txt"); std::string name;
        while(std::getline(list,name)) {
            if(name.empty()) continue;
            auto x=read(root+"/export/cases/"+name+"/input.bin",BLOCK_FRAME_WORDS);
            auto expected=read(root+"/export/cases/"+name+"/golden_output.bin",BLOCK_FRAME_WORDS);
            command(in,BLOCK_RUN,0,x); gesture_blocks56_axis(in,out); check(out,expected);
            if(!in.empty()) throw std::runtime_error("Unconsumed input");
            std::cout<<"PASS_CASE "<<name<<std::endl;
        }
        // Zero convolution parameters make both residual blocks exact identity.
        std::vector<float> zero(BLOCK_PARAM_WORDS,0.0f);
        for(int bank=0;bank<2;bank++) {
            command(in,BLOCK_LOAD,bank,zero); gesture_blocks56_axis(in,out);
            if(ack(out)!=(0xA5010300|bank)) throw std::runtime_error("Reload failed");
        }
        auto x=read(root+"/export/cases/random/input.bin",BLOCK_FRAME_WORDS);
        command(in,BLOCK_RUN,0,x); gesture_blocks56_axis(in,out); check(out,x);
        for(int bank=0;bank<2;bank++) {
            command(in,BLOCK_LOAD,bank,params[bank]); gesture_blocks56_axis(in,out); ack(out);
        }
        x=read(root+"/export/cases/gradient/input.bin",BLOCK_FRAME_WORDS);
        command(in,BLOCK_RUN,0,x); gesture_blocks56_axis(in,out);
        check(out,read(root+"/export/cases/gradient/golden_output.bin",BLOCK_FRAME_WORDS));
        std::cout<<"BLOCKS56_CSIM_PASS"<<std::endl; return 0;
    } catch(const std::exception& e) {std::cerr<<e.what()<<std::endl;return 1;}
}
