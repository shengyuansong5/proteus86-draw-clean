; Independent 8051 keypad/display example for proteus86-draw.
; Classic 12 MHz core, P0=A..DP high-active, P2=digits 1..8 low-active.
; P3.0..3 drive keypad rows; P3.4..7 read columns. One key at a time.
; Startup pattern: 01234567. An accepted press changes the last two digits:
; accepted-press counter modulo 16, then row*4+column key value.
; A stable release is required before the next press can be accepted.

DIGIT_INDEX     DATA    020H
DIGIT_MASK      DATA    021H
CANDIDATE       DATA    022H
QUALIFY_COUNT   DATA    023H
PRESS_LATCH     DATA    024H
PRESS_COUNT     DATA    025H

                CSEG AT 0000H
                LJMP START

                CSEG AT 0030H
START:
                MOV SP,#060H
                MOV 0A8H,#00H
                MOV 080H,#00H
                MOV 0A0H,#0FFH
                MOV 0B0H,#0FFH
                MOV DIGIT_INDEX,#00H
                MOV DIGIT_MASK,#0FEH
                MOV CANDIDATE,#0FFH
                MOV QUALIFY_COUNT,#00H
                MOV PRESS_LATCH,#00H
                MOV PRESS_COUNT,#00H
                MOV R0,#030H
                MOV A,#00H
INIT_PATTERN:
                MOV @R0,A
                INC R0
                INC A
                CJNE A,#08H,INIT_PATTERN

MAIN:
                LCALL DISPLAY_STEP
                LCALL KEY_TICK
                SJMP MAIN

; Display RAM 30H..37H contains hexadecimal values, not physical segment bits.
; Blank before changing segments to avoid switching with two digits enabled.
DISPLAY_STEP:
                MOV 0A0H,#0FFH
                MOV A,DIGIT_INDEX
                ADD A,#030H
                MOV R0,A
                MOV A,@R0
                MOV DPTR,#SEGMENTS
                MOVC A,@A+DPTR
                MOV 080H,A
                MOV A,DIGIT_MASK
                MOV 0A0H,A
                LCALL DIGIT_DWELL
                MOV 0A0H,#0FFH
                INC DIGIT_INDEX
                MOV A,DIGIT_MASK
                RL A
                MOV DIGIT_MASK,A
                MOV A,DIGIT_INDEX
                CJNE A,#08H,DISPLAY_DONE
                MOV DIGIT_INDEX,#00H
                MOV DIGIT_MASK,#0FEH
DISPLAY_DONE:
                RET

; About 1 ms at 12 MHz in the classic 12-clock mode. Loop overhead adds
; a small amount of time, so qualification is intentionally approximate.
DIGIT_DWELL:
                MOV R5,#02H
DWELL_OUTER:
                MOV R6,#250
DWELL_INNER:
                DJNZ R6,DWELL_INNER
                DJNZ R5,DWELL_OUTER
                RET

; MATRIX_SCAN returns FFH for no key or an ambiguous column mask in the first
; active row, otherwise row*4+column. Simultaneous keys are not supported.
; A raw state must repeat for 20 main-loop ticks before it is accepted.
KEY_TICK:
                LCALL MATRIX_SCAN
                CJNE A,CANDIDATE,NEW_CANDIDATE
                MOV A,QUALIFY_COUNT
                CJNE A,#20,QUALIFY_MORE
                MOV A,CANDIDATE
                CJNE A,#0FFH,STABLE_PRESS
                MOV PRESS_LATCH,#00H
                RET
STABLE_PRESS:
                MOV A,PRESS_LATCH
                JNZ KEY_DONE
                MOV PRESS_LATCH,#01H
                INC PRESS_COUNT
                ANL PRESS_COUNT,#00FH
                MOV 036H,PRESS_COUNT
                MOV 037H,CANDIDATE
KEY_DONE:
                RET
QUALIFY_MORE:
                INC QUALIFY_COUNT
                RET
NEW_CANDIDATE:
                MOV CANDIDATE,A
                MOV QUALIFY_COUNT,#00H
                RET

MATRIX_SCAN:
                MOV R2,#00H
                MOV R3,#0FEH
NEXT_ROW:
                MOV 0B0H,R3
                NOP
                NOP
                MOV A,0B0H
                ANL A,#0F0H
                CJNE A,#0F0H,FOUND_ROW
                MOV A,R3
                RL A
                ORL A,#0F0H
                MOV R3,A
                INC R2
                CJNE R2,#04H,NEXT_ROW
NO_KEY:
                MOV 0B0H,#0FFH
                MOV A,#0FFH
                RET
FOUND_ROW:
                CJNE A,#0E0H,TRY_COLUMN1
                MOV R4,#00H
                SJMP KEY_NUMBER
TRY_COLUMN1:
                CJNE A,#0D0H,TRY_COLUMN2
                MOV R4,#01H
                SJMP KEY_NUMBER
TRY_COLUMN2:
                CJNE A,#0B0H,TRY_COLUMN3
                MOV R4,#02H
                SJMP KEY_NUMBER
TRY_COLUMN3:
                CJNE A,#070H,NO_KEY
                MOV R4,#03H
KEY_NUMBER:
                MOV A,R2
                RL A
                RL A
                ADD A,R4
                MOV 0B0H,#0FFH
                RET

SEGMENTS:
                DB 03FH,006H,05BH,04FH,066H,06DH,07DH,007H
                DB 07FH,06FH,077H,07CH,039H,05EH,079H,071H
                END
