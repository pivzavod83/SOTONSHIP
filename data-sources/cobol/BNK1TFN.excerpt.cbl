       PROCESS CICS,NODYNAM,NSYMBOL(NATIONAL),TRUNC(STD)
       CBL CICS('SP,EDF')
      ******************************************************************
      *                                                                *
      *  Copyright IBM Corp. 2023                                      *
      *                                                                *
      ******************************************************************

       01 COMM-ADDR-SPLIT.
          03 COMM-ADDR-SPLIT1           PIC X(60).
          03 COMM-ADDR-SPLIT2           PIC X(60).
          03 COMM-ADDR-SPLIT3           PIC X(40).

       01 WS-CONVERSIONA.
          03 WS-CONVERT-PIC1            PIC X(13).
          03 WS-CONVERT-PIC1SP REDEFINES WS-CONVERT-PIC1.
             05 WS-CONVERT-PIC1-1ST     PIC X(10).
             05 WS-CONVERT-PIC1-POINT   PIC X.
             05 WS-CONVERT-PIC1-2ND     PIC XX.

       01 WS-CONVERSIONB.
          03 WS-CONVERT-PICX            PIC X(13).
          03 WS-CONVERT-SPLIT REDEFINES WS-CONVERT-PICX.
             05 WS-CONVERT-DEC          PIC 9(10).
             05 WS-CONVERT-POINT        PIC X.
             05 WS-CONVERT-REMAIN       PIC 99.

       01 WS-CONVERTED-VAL1             PIC S9(10)V99 VALUE 0.
       01 WS-CONVERTED-VAL2             PIC S9(10)V99 VALUE 0.
       01 WS-CONVERTED-VAL3             PIC S9(10)V99 VALUE 0.
       01 WS-CONVERTED-VAL4             PIC S9(10)V99 VALUE 0.
       RECEIVE-MAP SECTION.
       RM010.
      *
      *    Retrieve the data
      *
           EXEC CICS
              RECEIVE MAP('BNK1TF')
              MAPSET('BNK1TFM')
              INTO(BNK1TFI)
              RESP(WS-CICS-RESP)
              RESP2(WS-CICS-RESP2)
           END-EXEC.

           IF WS-CICS-RESP NOT = DFHRESP(NORMAL)
      *
      *       Preserve the RESP and RESP2, then set up the
      *       standard ABEND info before getting the applid,
      *       date/time etc. and linking to the Abend Handler
      *       program.
      *
              INITIALIZE ABNDINFO-REC
              MOVE EIBRESP    TO ABND-RESPCODE
              MOVE EIBRESP2   TO ABND-RESP2CODE
      *
      *       Get supplemental information
