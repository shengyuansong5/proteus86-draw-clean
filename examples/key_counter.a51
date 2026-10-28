; Independent native test firmware, NOT coursework or an offline ISA executor.
; 12 MHz classic 8051. Active-low button P3.2, active-low binary count on P1.
; About 30 ms stable press/release qualification; one response per held press.
        CSEG AT 0000H
        MOV SP,#060H
        MOV R0,#0
        MOV 090H,#0FFH
WAITKEY:
        JB 0B2H,WAITKEY
        LCALL DELAY
        JB 0B2H,WAITKEY
        INC R0
        MOV A,R0
        CPL A
        MOV 090H,A
WAITUP:
        JNB 0B2H,WAITUP
        LCALL DELAY
        JNB 0B2H,WAITUP
        SJMP WAITKEY
DELAY:
        MOV R5,#60
OUTER:
        MOV R6,#250
INNER:
        DJNZ R6,INNER
        DJNZ R5,OUTER
        RET
        END
