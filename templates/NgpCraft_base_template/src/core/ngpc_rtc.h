/*
 * ngpc_rtc.h - Real-Time Clock access
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * The NGPC has a battery-backed RTC that provides date/time and alarm.
 * Values are in BCD format (e.g. hour=0x23 means 23:xx).
 * Access via BIOS calls (RTCGET, ALARMSET, ALARMDOWNSET).
 */

#ifndef NGPC_RTC_H
#define NGPC_RTC_H

#include "ngpc_types.h"

/* Date/time structure (BCD-encoded fields). */
typedef struct {
    u8 year;        /* 00-99 (BCD, add 1900 or 2000 as needed) */
    u8 month;       /* 01-12 (BCD) */
    u8 day;         /* 01-31 (BCD) */
    u8 hour;        /* 00-23 (BCD) */
    u8 minute;      /* 00-59 (BCD) */
    u8 second;      /* 00-59 (BCD) */
    u8 extra;       /* bits 7-4: leap year counter, bits 3-0: weekday */
} NgpcTime;

/* Alarm structure. */
typedef struct {
    u8 day;         /* Day of month 01-31 (BCD) */
    u8 hour;        /* Hour 00-23 (BCD) */
    u8 minute;      /* Minute 00-59 (BCD) */
    u8 code;        /* Reserved / return code */
} NgpcAlarm;

/* Helper macros for BCD values. */
#define BCD_TO_BIN(bcd) (((bcd) >> 4) * 10 + ((bcd) & 0x0F))
#define BIN_TO_BCD(bin) ((((bin) / 10) << 4) | ((bin) % 10))

/* Read current date/time from the RTC.
 * Fills all fields of the NgpcTime struct (BCD format). */
void ngpc_rtc_get(NgpcTime *t);

/* Set an alarm that fires while the game is running.
 * The RTC alarm interrupt (0x6FC8) will be triggered.
 * Install a handler with ngpc_rtc_set_alarm_handler() first. */
void ngpc_rtc_set_alarm(NgpcAlarm *a);

/* Set a wake-up alarm (powers on the NGPC at the given time).
 * Works even when the console is off. */
void ngpc_rtc_set_wake(NgpcAlarm *a);

/* Install a custom RTC alarm interrupt handler.
 * handler: function pointer, called when alarm triggers. */
void ngpc_rtc_set_alarm_handler(void (*handler)(void));

/* Get weekday from NgpcTime (0=Sunday .. 6=Saturday). */
#define NGPC_RTC_WEEKDAY(t) ((t)->extra & 0x0F)

/* Get leap year counter from NgpcTime (0-3). */
#define NGPC_RTC_LEAPYEAR(t) (((t)->extra >> 4) & 0x0F)

#endif /* NGPC_RTC_H */
