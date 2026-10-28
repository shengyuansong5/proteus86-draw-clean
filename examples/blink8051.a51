; Independent Proteus tool validation fixture, not coursework firmware.
; 12 MHz classic 8051: alternate active-low P1 LEDs and ULN2003 inputs.
        CSEG AT 0000H
        MOV 090H,#0FFH
        MOV 0A0H,#00H
LOOP:   MOV 090H,#00H
        MOV 0A0H,#07FH
        LCALL DELAY
        MOV 090H,#0FFH
        MOV 0A0H,#00H
        LCALL DELAY
        SJMP LOOP
DELAY:  MOV R7,#8
OUTER:  MOV R6,#250
MIDDLE: MOV R5,#250
INNER:  DJNZ R5,INNER
        DJNZ R6,MIDDLE
        DJNZ R7,OUTER
        RET
        END
