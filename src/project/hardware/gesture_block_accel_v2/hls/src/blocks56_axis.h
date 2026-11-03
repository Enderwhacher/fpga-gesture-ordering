#ifndef GESTURE_BLOCKS56_AXIS_H
#define GESTURE_BLOCKS56_AXIS_H
#include <ap_axi_sdata.h>
#include <hls_stream.h>
#include <stdint.h>

using block_axis_word=ap_axiu<32,0,0,0>;
constexpr unsigned BLOCK_MAGIC=0x47534232;
constexpr unsigned BLOCK_VERSION=1;
constexpr unsigned BLOCK_LOAD=1;
constexpr unsigned BLOCK_RUN=2;
constexpr unsigned BLOCK_PING=3;
constexpr int BLOCK_FRAME_WORDS=40*28*28;
constexpr int BLOCK_PARAM_WORDS=20712;
inline float block_float(ap_uint<32> bits) {
    union {uint32_t u; float f;} value; value.u=bits.to_uint(); return value.f;
}
inline ap_uint<32> block_bits(float f) {
    union {uint32_t u; float f;} value; value.f=f; return value.u;
}
inline float block_unpack(ap_uint<64> pair,int pixel) {
    return block_float(pixel&1?ap_uint<32>(pair.range(63,32)):ap_uint<32>(pair.range(31,0)));
}
inline ap_uint<64> block_pair(float low,float high) {
    ap_uint<64> pair; pair.range(31,0)=block_bits(low); pair.range(63,32)=block_bits(high); return pair;
}
void gesture_blocks56_axis(hls::stream<block_axis_word>& s_axis,hls::stream<block_axis_word>& m_axis);
#endif
