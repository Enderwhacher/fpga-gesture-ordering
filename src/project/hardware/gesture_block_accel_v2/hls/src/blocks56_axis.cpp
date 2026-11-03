#include "blocks56_axis.h"

static float relu(float x) { return x>0.0f?x:0.0f; }

static float dot16(const float x[16],const float w[16]) {
#pragma HLS INLINE
    float p[16],a[8],b[4],c[2];
#pragma HLS ARRAY_PARTITION variable=p complete
#pragma HLS ARRAY_PARTITION variable=a complete
#pragma HLS ARRAY_PARTITION variable=b complete
#pragma HLS ARRAY_PARTITION variable=c complete
    for(int i=0;i<16;i++) {
#pragma HLS UNROLL
        p[i]=x[i]*w[i];
    }
    for(int i=0;i<8;i++) {
#pragma HLS UNROLL
        a[i]=p[2*i]+p[2*i+1];
    }
    for(int i=0;i<4;i++) {
#pragma HLS UNROLL
        b[i]=a[2*i]+a[2*i+1];
    }
    for(int i=0;i<2;i++) {
#pragma HLS UNROLL
        c[i]=b[2*i]+b[2*i+1];
    }
    return c[0]+c[1];
}

static float dot25(const float x[5][5],const float w[25],float bias) {
#pragma HLS INLINE
    float p[32],a[16],b[8],c[4],d[2];
#pragma HLS ARRAY_PARTITION variable=p complete
#pragma HLS ARRAY_PARTITION variable=a complete
#pragma HLS ARRAY_PARTITION variable=b complete
#pragma HLS ARRAY_PARTITION variable=c complete
#pragma HLS ARRAY_PARTITION variable=d complete
    for(int i=0;i<32;i++) {
#pragma HLS UNROLL
        p[i]=i<25?x[i/5][i%5]*w[i]:(i==25?bias:0.0f);
    }
    for(int i=0;i<16;i++) {
#pragma HLS UNROLL
        a[i]=p[2*i]+p[2*i+1];
    }
    for(int i=0;i<8;i++) {
#pragma HLS UNROLL
        b[i]=a[2*i]+a[2*i+1];
    }
    for(int i=0;i<4;i++) {
#pragma HLS UNROLL
        c[i]=b[2*i]+b[2*i+1];
    }
    for(int i=0;i<2;i++) {
#pragma HLS UNROLL
        d[i]=c[2*i]+c[2*i+1];
    }
    return d[0]+d[1];
}

static void read_pw(hls::stream<block_axis_word>& in,ap_uint<64> weights[8][4][340],int bank,bool projection) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=weights complete dim=1
#pragma HLS ARRAY_PARTITION variable=weights complete dim=2
    const int ci=projection?120:40,co=projection?40:120;
    for(int o=0;o<co;o++) {
        for(int i=0;i<((ci+15)/16)*16;i+=2) {
#pragma HLS PIPELINE II=2
            ap_uint<64> pair=0;
            if(i<ci) {
                pair.range(31,0)=in.read().data;
                pair.range(63,32)=in.read().data;
            }
            int tile=bank*85+(projection?45:0)+(o/8)*((ci+15)/16)+i/16;
            int lane_pair=(i%16)/2;
            weights[o%8][lane_pair%4][tile*2+lane_pair/4]=pair;
        }
    }
}

static void pointwise(const ap_uint<64> src[8][15][392],ap_uint<64> dst[8][15][392],
                     const ap_uint<64> residual[8][5][392],const ap_uint<64> weights[8][4][340],
                     const float expand_bias[2][120],const float project_bias[2][40],int bank,bool projection) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=src complete dim=1
#pragma HLS ARRAY_PARTITION variable=dst complete dim=1
#pragma HLS ARRAY_PARTITION variable=residual complete dim=1
#pragma HLS ARRAY_PARTITION variable=weights complete dim=1
#pragma HLS ARRAY_PARTITION variable=weights complete dim=2
    const int out_tiles=projection?5:15,in_tiles=projection?8:3;
    float acc[8][784];
#pragma HLS ARRAY_PARTITION variable=acc complete dim=1
#pragma HLS BIND_STORAGE variable=acc type=ram_2p impl=bram
pw_out_tiles:
    for(int ob=0;ob<out_tiles;ob++) {
pw_init:
        for(int p=0;p<784;p++) {
#pragma HLS PIPELINE II=1
            for(int o=0;o<8;o++) {
#pragma HLS UNROLL
                acc[o][p]=projection?project_bias[bank][ob*8+o]:expand_bias[bank][ob*8+o];
            }
        }
pw_in_tiles:
        for(int ib=0;ib<in_tiles;ib++) {
            float w[8][16];
#pragma HLS ARRAY_PARTITION variable=w complete dim=0
            int tile=bank*85+(projection?45:0)+ob*in_tiles+ib;
            for(int o=0;o<8;o++) {
#pragma HLS UNROLL
                for(int pair_index=0;pair_index<8;pair_index++) {
#pragma HLS UNROLL
                    ap_uint<64> pair=weights[o][pair_index%4][tile*2+pair_index/4];
                    w[o][2*pair_index]=block_float(pair.range(31,0));
                    w[o][2*pair_index+1]=block_float(pair.range(63,32));
                }
            }
pw_pixels:
            for(int p=0;p<784;p++) {
#pragma HLS PIPELINE II=1
                float x[16];
#pragma HLS ARRAY_PARTITION variable=x complete
                for(int i=0;i<16;i++) {
#pragma HLS UNROLL
                    int channel=ib*16+i;
                    x[i]=channel<(projection?120:40)?block_unpack(src[channel%8][channel/8][p/2],p):0.0f;
                }
                for(int o=0;o<8;o++) {
#pragma HLS UNROLL
                    acc[o][p]=acc[o][p]+dot16(x,w[o]);
                }
            }
        }
        float even[8];
#pragma HLS ARRAY_PARTITION variable=even complete
pw_store:
        for(int p=0;p<784;p++) {
#pragma HLS PIPELINE II=1
            for(int o=0;o<8;o++) {
#pragma HLS UNROLL
                float value=acc[o][p];
                value=projection?value+block_unpack(residual[o][ob][p/2],p):relu(value);
                if((p&1)==0) even[o]=value;
                else dst[o][ob][p/2]=block_pair(even[o],value);
            }
        }
    }
}

static void depthwise(const ap_uint<64> src[8][15][392],ap_uint<64> dst[8][15][392],
                      const float weights[2][2][60][25],const float bias[2][120],int bank) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=src complete dim=1
#pragma HLS ARRAY_PARTITION variable=dst complete dim=1
#pragma HLS ARRAY_PARTITION variable=weights complete dim=1
#pragma HLS ARRAY_PARTITION variable=weights complete dim=4
dw_groups:
    for(int group=0;group<60;group++) {
        float lines[2][4][32],window[2][5][5],w[2][25],even[2];
#pragma HLS ARRAY_PARTITION variable=lines complete dim=1
#pragma HLS ARRAY_PARTITION variable=lines complete dim=2
#pragma HLS BIND_STORAGE variable=lines type=ram_s2p impl=bram
#pragma HLS ARRAY_PARTITION variable=window complete dim=0
#pragma HLS ARRAY_PARTITION variable=w complete dim=0
#pragma HLS ARRAY_PARTITION variable=even complete
        for(int lane=0;lane<2;lane++) {
#pragma HLS UNROLL
            for(int k=0;k<25;k++) {
#pragma HLS UNROLL
                w[lane][k]=weights[lane][bank][group][k];
                window[lane][k/5][k%5]=0;
            }
        }
        for(int x=0;x<32;x++) {
#pragma HLS PIPELINE II=1
            for(int lane=0;lane<2;lane++) {
#pragma HLS UNROLL
                for(int row=0;row<4;row++) {
#pragma HLS UNROLL
                    lines[lane][row][x]=0;
                }
            }
        }
dw_rows:
        for(int py=0;py<32;py++) {
dw_columns:
            for(int px=0;px<32;px++) {
#pragma HLS PIPELINE II=1
                for(int lane=0;lane<2;lane++) {
#pragma HLS UNROLL
                    int ch=group*2+lane;
                    float incoming=0;
                    if(py>=2 && py<30 && px>=2 && px<30) {
                        int p=(py-2)*28+px-2;
                        incoming=block_unpack(src[ch%8][ch/8][p/2],p);
                    }
                    float column[5];
#pragma HLS ARRAY_PARTITION variable=column complete
                    for(int row=0;row<4;row++) {
#pragma HLS UNROLL
                        column[row]=lines[lane][row][px];
                    }
                    column[4]=incoming;
                    for(int row=0;row<4;row++) {
#pragma HLS UNROLL
                        lines[lane][row][px]=column[row+1];
                    }
                    for(int row=0;row<5;row++) {
#pragma HLS UNROLL
                        for(int col=0;col<4;col++) {
#pragma HLS UNROLL
                            window[lane][row][col]=window[lane][row][col+1];
                        }
                        window[lane][row][4]=column[row];
                    }
                    if(py>=4 && px>=4) {
                        int p=(py-4)*28+px-4;
                        float value=relu(dot25(window[lane],w[lane],bias[bank][ch]));
                        if((p&1)==0) even[lane]=value;
                        else dst[ch%8][ch/8][p/2]=block_pair(even[lane],value);
                    }
                }
            }
        }
    }
}

static void squeeze(const ap_uint<64> src[8][15][392],float mean[120]) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=src complete dim=1
#pragma HLS ARRAY_PARTITION variable=mean complete
    for(int tile=0;tile<15;tile++) {
        float partial[8][28],sum[8];
#pragma HLS ARRAY_PARTITION variable=partial complete dim=0
#pragma HLS ARRAY_PARTITION variable=sum complete
        for(int col=0;col<28;col++) {
#pragma HLS PIPELINE II=1
            for(int lane=0;lane<8;lane++) {
#pragma HLS UNROLL
                partial[lane][col]=0;
            }
        }
        for(int row=0;row<28;row++) {
gap_columns:
            for(int col=0;col<28;col++) {
#pragma HLS PIPELINE II=1
                for(int lane=0;lane<8;lane++) {
#pragma HLS UNROLL
                    partial[lane][col]+=block_unpack(src[lane][tile][row*14+col/2],col);
                }
            }
        }
        for(int lane=0;lane<8;lane++) {
#pragma HLS UNROLL
            sum[lane]=0;
        }
        for(int col=0;col<28;col++) {
            for(int lane=0;lane<8;lane++) {
#pragma HLS UNROLL
                sum[lane]+=partial[lane][col];
            }
        }
        for(int lane=0;lane<8;lane++) {
#pragma HLS UNROLL
            mean[tile*8+lane]=sum[lane]*(1.0f/784.0f);
        }
    }
}

static void se_layer(const float src[120],float dst[120],const float weights[15360],
                     const float bias1[2][32],const float bias2[2][120],int bank,bool second) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=src complete
#pragma HLS ARRAY_PARTITION variable=dst complete
    int ci=second?32:120,co=second?120:32;
    int offset=bank*7680+(second?3840:0);
    for(int o=0;o<co;o++) {
        float partial[8];
#pragma HLS ARRAY_PARTITION variable=partial complete
        for(int i=0;i<8;i++) {
#pragma HLS UNROLL
            partial[i]=0;
        }
        for(int base=0;base<ci;base+=8) {
            for(int lane=0;lane<8;lane++) {
#pragma HLS PIPELINE II=1
                partial[lane]+=src[base+lane]*weights[offset+o*ci+base+lane];
            }
        }
        float sum=(partial[0]+partial[1])+(partial[2]+partial[3]);
        sum+= (partial[4]+partial[5])+(partial[6]+partial[7]);
        sum+=second?bias2[bank][o]:bias1[bank][o];
        if(second) {
            float gate=sum*(1.0f/6.0f)+0.5f;
            dst[o]=gate<0?0:(gate>1?1:gate);
        } else dst[o]=relu(sum);
    }
}

static void scale(const ap_uint<64> src[8][15][392],ap_uint<64> dst[8][15][392],const float gate[120]) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=src complete dim=1
#pragma HLS ARRAY_PARTITION variable=dst complete dim=1
#pragma HLS ARRAY_PARTITION variable=gate complete
    for(int tile=0;tile<15;tile++) {
        for(int p=0;p<392;p++) {
#pragma HLS PIPELINE II=1
            for(int lane=0;lane<8;lane++) {
#pragma HLS UNROLL
                ap_uint<64> input=src[lane][tile][p];
                float factor=gate[tile*8+lane];
                dst[lane][tile][p]=block_pair(block_unpack(input,0)*factor,block_unpack(input,1)*factor);
            }
        }
    }
}

static void emit_status(hls::stream<block_axis_word>& out,unsigned value) {
#pragma HLS INLINE
    block_axis_word word; word.data=value; word.keep=0xF; word.strb=0xF; word.last=1; out.write(word);
}

void gesture_blocks56_axis(hls::stream<block_axis_word>& s_axis,hls::stream<block_axis_word>& m_axis) {
#pragma HLS INTERFACE mode=axis port=s_axis
#pragma HLS INTERFACE mode=axis port=m_axis
#pragma HLS INTERFACE mode=s_axilite port=return bundle=control
#pragma HLS ALLOCATION function instances=pointwise limit=1
#pragma HLS ALLOCATION function instances=depthwise limit=1
#pragma HLS ALLOCATION function instances=se_layer limit=1
    // Two FP32 values occupy one 64-bit URAM word. This is bit packing, not
    // quantization, and avoids wasting half of each native wide URAM port.
    static ap_uint<64> a[8][15][392],b[8][15][392],residual[8][5][392];
    static ap_uint<64> pw[8][4][340];
    static float dw[2][2][60][25],se[15360];
    static float eb[2][120],db[2][120],s1b[2][32],s2b[2][120],pb[2][40];
    static ap_uint<2> loaded=0;
#pragma HLS ARRAY_PARTITION variable=a complete dim=1
#pragma HLS ARRAY_PARTITION variable=b complete dim=1
#pragma HLS ARRAY_PARTITION variable=residual complete dim=1
#pragma HLS BIND_STORAGE variable=a type=ram_2p impl=uram
#pragma HLS BIND_STORAGE variable=b type=ram_2p impl=uram
#pragma HLS BIND_STORAGE variable=residual type=ram_2p impl=bram
#pragma HLS ARRAY_PARTITION variable=pw complete dim=1
#pragma HLS ARRAY_PARTITION variable=pw complete dim=2
#pragma HLS BIND_STORAGE variable=pw type=ram_2p impl=bram
#pragma HLS ARRAY_PARTITION variable=dw complete dim=1
#pragma HLS ARRAY_PARTITION variable=dw complete dim=4
#pragma HLS BIND_STORAGE variable=dw type=ram_2p impl=lutram
#pragma HLS BIND_STORAGE variable=se type=ram_2p impl=bram
#pragma HLS ARRAY_PARTITION variable=eb cyclic factor=8 dim=2
#pragma HLS ARRAY_PARTITION variable=db cyclic factor=4 dim=2
#pragma HLS ARRAY_PARTITION variable=pb cyclic factor=8 dim=2
    unsigned magic=s_axis.read().data.to_uint();
    unsigned op=s_axis.read().data.to_uint();
    unsigned bank=s_axis.read().data.to_uint();
    unsigned version=s_axis.read().data.to_uint();
    if(magic!=BLOCK_MAGIC || version!=BLOCK_VERSION || bank>1) {emit_status(m_axis,0xE1000001); return;}
    if(op==BLOCK_PING) {emit_status(m_axis,0xA5010000|((unsigned)loaded<<8)); return;}
    if(op==BLOCK_LOAD) {
        loaded[bank]=0;
        read_pw(s_axis,pw,bank,false);
        for(int c=0;c<120;c++) {
            for(int k=0;k<25;k++) {
#pragma HLS PIPELINE II=1
                dw[c%2][bank][c/2][k]=block_float(s_axis.read().data);
            }
        }
        for(int k=0;k<7680;k++) {
#pragma HLS PIPELINE II=1
            se[bank*7680+k]=block_float(s_axis.read().data);
        }
        read_pw(s_axis,pw,bank,true);
        for(int c=0;c<120;c++) {
#pragma HLS PIPELINE II=1
            eb[bank][c]=block_float(s_axis.read().data);
        }
        for(int c=0;c<120;c++) {
#pragma HLS PIPELINE II=1
            db[bank][c]=block_float(s_axis.read().data);
        }
        for(int c=0;c<32;c++) {
#pragma HLS PIPELINE II=1
            s1b[bank][c]=block_float(s_axis.read().data);
        }
        for(int c=0;c<120;c++) {
#pragma HLS PIPELINE II=1
            s2b[bank][c]=block_float(s_axis.read().data);
        }
        for(int c=0;c<40;c++) {
#pragma HLS PIPELINE II=1
            pb[bank][c]=block_float(s_axis.read().data);
        }
        loaded[bank]=1; emit_status(m_axis,0xA5010000|((unsigned)loaded<<8)|bank); return;
    }
    if(op!=BLOCK_RUN || loaded!=3) {emit_status(m_axis,0xE1000002); return;}
    for(int c=0;c<40;c++) {
        for(int p=0;p<392;p++) {
#pragma HLS PIPELINE II=2
            ap_uint<64> pair;
            pair.range(31,0)=s_axis.read().data;
            pair.range(63,32)=s_axis.read().data;
            a[c%8][c/8][p]=pair;
        }
    }
    for(int block=0;block<2;block++) {
        for(int tile=0;tile<5;tile++) {
            for(int p=0;p<392;p++) {
#pragma HLS PIPELINE II=1
                for(int lane=0;lane<8;lane++) {
#pragma HLS UNROLL
                    residual[lane][tile][p]=a[lane][tile][p];
                }
            }
        }
        pointwise(a,b,residual,pw,eb,pb,block,false);
        depthwise(b,a,dw,db,block);
        float mean[120],hidden[120],gate[120];
#pragma HLS ARRAY_PARTITION variable=mean complete
#pragma HLS ARRAY_PARTITION variable=hidden complete
#pragma HLS ARRAY_PARTITION variable=gate complete
        squeeze(a,mean);
        se_layer(mean,hidden,se,s1b,s2b,block,false);
        se_layer(hidden,gate,se,s1b,s2b,block,true);
        scale(a,b,gate);
        pointwise(b,a,residual,pw,eb,pb,block,true);
    }
    for(int c=0;c<40;c++) {
        for(int p=0;p<784;p++) {
#pragma HLS PIPELINE II=1
            block_axis_word word; word.data=block_bits(block_unpack(a[c%8][c/8][p/2],p));
            word.keep=0xF; word.strb=0xF; word.last=(c==39 && p==783); m_axis.write(word);
        }
    }
}
