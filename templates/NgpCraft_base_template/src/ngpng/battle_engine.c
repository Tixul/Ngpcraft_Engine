/*
 * battle_engine.c — JRPG Pokémon-style 1v1 turn-based combat.
 *
 * Visual layout faithful to the NgpCraft demo overlay
 * (ngpng_prepare_random_encounter_overlay / ngpng_encounter_draw_stats / etc).
 * Parametric backend (monster_table, item_table, BE_* macros) is kept from the
 * engine's mech system.
 *
 * Layout (text cells, 20×19) :
 *
 *     +---------------+--------+
 *     | (1,1) ENEMY   | enemy  |
 *     | (1,3) HP X/Y  | sprite |   ← enemy sprite @ pixel (112, 18)
 *     +---------------+--------+
 *     |               | (9,8)  HERO
 *     | hero sprite   | (9,10) HP X/Y
 *     |  (8, 44)      |
 *     +---------------+--------+
 *     | FIGHT (4,14)    ITEM (14,14)
 *     | GUARD (4,16)    RUN  (14,16)
 *     +-------------------------+
 *     | result lines (rows 14-17 when DIALOG view shows post-action text)
 */
#include "ngpc_hw.h"
#include "ngpc_gfx.h"
#include "ngpc_sprite.h"
#include "ngpc_text.h"
#include "ngpc_input.h"
#include "ngpc_math.h"

#include "../../optional/ngpc_menu/ngpc_menu.h"
#include "../../optional/ngpc_inventory/ngpc_inventory.h"

#include "../../GraphX/gen/battle_engine.h"
#include "../../GraphX/gen/battle_engine_assets.h"
#include "../../GraphX/gen/item_table.h"
#include "../../GraphX/gen/monster_table.h"

#if !defined(NGP_ENABLE_SOUND) || !(NGP_ENABLE_SOUND)
static void Sfx_Play(unsigned char id) { (void)id; }
#else
extern void Sfx_Play(unsigned char id);
#endif

extern void battle_engine_play_bgm(u8 bgm_id);
extern void battle_engine_emit_event(u8 event_id);

#define BE_RGB(r, g, b)  ((u16)(((r) & 0xF) | (((g) & 0xF) << 4) | (((b) & 0xF) << 8)))

/* HUD plane = SCR1 (front). BG tilemap = SCR2 (back). HUD palette slot 15. */
#define BE_HUD_PLANE  GFX_SCR1
#define BE_HUD_PAL    15u

/* Battle views (state machine). */
#define BV_OFF       0u
#define BV_COMMAND   1u   /* 2x2 cmd grid : FIGHT / ITEM / GUARD / RUN */
#define BV_ITEM      2u   /* item sub-menu (linear list using NgpcMenu) */
#define BV_ANIM      3u   /* attack animation : sprite knockback wiggle */
#define BV_DIALOG    4u   /* multi-line result text waiting for A press */

/* After-dialog continuations. */
#define POST_NONE        0u
#define POST_RETURN_CMD  1u
#define POST_RETURN_ITEM 2u
#define POST_ENEMY_TURN  3u
#define POST_END_WIN     4u
#define POST_END_LOSE    5u
#define POST_END_RUN     6u

/* ANIM state : sprite knockback timing. */
#define BE_ANIM_TICKS    10u   /* matches demo NGPNG_ENCOUNTER_ANIM_TICKS */
#define BE_ANIM_PLAYER   0u
#define BE_ANIM_ENEMY    1u

/* Item sub-menu cap. */
#define BE_ITEM_MENU_MAX  8u

/* Result lines : up to 4 lines (rows 14..17 in DIALOG view). */
#define BE_MAX_RESULT_LINES  4u

/* ============================================================ */
/* State                                                         */
/* ============================================================ */

static u8  s_active;
static u8  s_battle_view;
static u8  s_dialog_post;
static u8  s_guard_active;
static u8  s_player_hp;
static u8  s_enemy_hp;
static u8  s_monster_idx;
static u16 s_frame_counter;

/* Knockback offsets (signed pixels, applied each frame in render). */
static s8  s_hero_dx,  s_hero_dy;
static s8  s_enemy_dx, s_enemy_dy;
static u8  s_anim_timer;
static u8  s_anim_actor;   /* PLAYER vs ENEMY */
static u8  s_anim_hit;     /* 1 = target gets a shake */

/* Dirty flags (avoid per-frame text re-writes → no flicker). */
static u8  s_stats_dirty;
static u8  s_menu_dirty;
static u8  s_prev_player_hp;
static u8  s_prev_enemy_hp;
static u8  s_cmd_sel;      /* 0..3 grid index */
static u8  s_prev_cmd_sel;
static u8  s_cmd_enabled[4];

/* Result lines accumulator — DIALOG view prints these at rows 14..17. */
static char s_result_lines[BE_MAX_RESULT_LINES][20];
static u8   s_result_count;

/* Item sub-menu storage. */
static char        s_item_label_storage[BE_ITEM_MENU_MAX][20];
static const char *s_item_labels[BE_ITEM_MENU_MAX];
static u8          s_item_id_map[BE_ITEM_MENU_MAX];
static u8          s_item_count;

static NgpcMenu      s_item_menu;
static NgpcInventory s_inventory;

/* 2x2 cmd grid : positions match demo (autorun L603-606). */
static const u8 BE_CMD_COL[4] = { 4u, 14u,  4u, 14u };
static const u8 BE_CMD_ROW[4] = {14u, 14u, 16u, 16u };
static const u8 BE_CUR_COL[4] = { 2u, 12u,  2u, 12u };  /* cursor col (one before label) */
static const u8 BE_CUR_ROW[4] = {14u, 14u, 16u, 16u };
static const char *BE_CMD_LABEL[4] = { "FIGHT", "ITEM", "GUARD", "RUN" };

/* ============================================================ */
/* Small helpers                                                 */
/* ============================================================ */

static u8 be_rand_pct(void)             { return (u8)(ngpc_qrandom() % 100u); }
static u8 be_rand_in_range(u8 b, u8 r)  { return (r == 0u) ? b : (u8)(b + (ngpc_qrandom() % r)); }
static void be_play_sfx(u8 id)          { if (id != 0u) Sfx_Play(id); }
static void be_emit(u8 id)              { if (id != 0u) battle_engine_emit_event(id); }
static void be_grant_var(u8 idx, u8 amt, u8 clamp) { (void)idx; (void)amt; (void)clamp; }
static u8 be_sub_floor0(u8 a, u8 b)     { return (a >= b) ? (u8)(a - b) : 0u; }

/* u16 → decimal string in buf, max 5 digits, returns nb chars written. */
static u8 be_u16_to_str(char *buf, u16 v)
{
    char tmp[6];
    u8 len = 0u;
    u8 i;
    if (v == 0u) { buf[0] = '0'; return 1u; }
    while (v > 0u && len < 5u) {
        tmp[len++] = (char)('0' + (v % 10u));
        v = (u16)(v / 10u);
    }
    for (i = 0u; i < len; i++) buf[i] = tmp[len - 1u - i];
    return len;
}

/* Print 20 spaces at (col, row) to clear a row. */
static void be_clear_row(u8 row)
{
    ngpc_text_print(BE_HUD_PLANE, BE_HUD_PAL, 0u, row,
                    "                    ");
}

/* Print "LABEL XX/YY" at (col, row), padded with trailing spaces to 11 chars
 * so it overwrites any longer previous value cleanly.  Demo-style.        */
static void be_print_ratio_line(u8 col, u8 row, const char *label, u16 cur, u16 max)
{
    char buf[12];
    u8 pos = 0u;
    const char *p = label;
    while (*p && pos < 4u) buf[pos++] = *p++;
    buf[pos++] = ' ';
    pos = (u8)(pos + be_u16_to_str(&buf[pos], cur));
    buf[pos++] = '/';
    pos = (u8)(pos + be_u16_to_str(&buf[pos], max));
    while (pos < 11u) buf[pos++] = ' ';
    buf[pos] = '\0';
    ngpc_text_print(BE_HUD_PLANE, BE_HUD_PAL, col, row, buf);
}

/* Print a name padded to <width> chars to overwrite old text (e.g. previous
 * enemy with a longer name).                                              */
static void be_print_name(u8 col, u8 row, const char *name, u8 width)
{
    char buf[12];
    u8 pos = 0u;
    if (width > 11u) width = 11u;
    if (name != 0) {
        while (*name && pos < width) buf[pos++] = *name++;
    }
    while (pos < width) buf[pos++] = ' ';
    buf[pos] = '\0';
    ngpc_text_print(BE_HUD_PLANE, BE_HUD_PAL, col, row, buf);
}

/* ============================================================ */
/* Result-lines accumulator                                      */
/* ============================================================ */

static void be_result_clear(void)
{
    u8 i, j;
    for (i = 0u; i < BE_MAX_RESULT_LINES; i++) {
        for (j = 0u; j < 19u; j++) s_result_lines[i][j] = ' ';
        s_result_lines[i][19] = '\0';
    }
    s_result_count = 0u;
}

static void be_result_push(const char *line)
{
    u8 i;
    if (s_result_count >= BE_MAX_RESULT_LINES || line == 0) return;
    for (i = 0u; i < 19u && line[i] != '\0'; i++) {
        s_result_lines[s_result_count][i] = line[i];
    }
    while (i < 19u) s_result_lines[s_result_count][i++] = ' ';
    s_result_lines[s_result_count][19] = '\0';
    s_result_count++;
}

/* Build "<ACTOR> <ACTION> <N>" line — demo build_damage_line. */
static void be_result_push_damage(const char *actor, const char *action, u8 dmg, u8 crit)
{
    char buf[20];
    u8 pos = 0u;
    const char *p;
    p = actor; while (*p && pos < 6u) buf[pos++] = *p++;
    buf[pos++] = ' ';
    p = action; while (*p && pos < 13u) buf[pos++] = *p++;
    buf[pos++] = ' ';
    pos = (u8)(pos + be_u16_to_str(&buf[pos], (u16)dmg));
    if (crit) {
        if (pos < 16u) buf[pos++] = '!';
        if (pos < 17u) buf[pos++] = '!';
    }
    while (pos < 19u) buf[pos++] = ' ';
    buf[pos] = '\0';
    be_result_push(buf);
}

/* Render all accumulated result lines (rows 14..17) and a "A CONTINUE" hint
 * on the line right after — overwriting menu cells.                       */
static void be_result_render(void)
{
    u8 i;
    for (i = 0u; i < BE_MAX_RESULT_LINES; i++) {
        be_clear_row((u8)(14u + i));
        if (i < s_result_count) {
            ngpc_text_print(BE_HUD_PLANE, BE_HUD_PAL, 1u, (u8)(14u + i),
                            s_result_lines[i]);
        }
    }
    /* Hint on last row regardless of how many lines we used. */
    ngpc_text_print(BE_HUD_PLANE, BE_HUD_PAL, 12u, 17u, BE_DIALOG_PRESS_HINT);
}

/* ============================================================ */
/* Item menu rebuild (dynamic, based on inventory)               */
/* ============================================================ */

static void be_build_item_menu(void)
{
    u8 n;
    s_item_count = 0u;
#if ITEM_COUNT > 0u
    {
        u8 i;
        u8 qty;
        for (i = 0u; i < ITEM_COUNT && s_item_count < BE_ITEM_MENU_MAX; i++) {
            if ((g_item_table[i].flags & ITEM_FLAG_USABLE_IN_BATTLE) == 0u) continue;
            qty = ngpc_inv_has(&s_inventory, i);
            if (qty == 0u) continue;
            /* "I<id> x<qty>" — v1.5 will use real item names. */
            s_item_label_storage[s_item_count][0] = 'I';
            s_item_label_storage[s_item_count][1] = (char)('0' + (i / 10u));
            s_item_label_storage[s_item_count][2] = (char)('0' + (i % 10u));
            s_item_label_storage[s_item_count][3] = ' ';
            s_item_label_storage[s_item_count][4] = 'x';
            s_item_label_storage[s_item_count][5] = (char)('0' + (qty / 10u));
            s_item_label_storage[s_item_count][6] = (char)('0' + (qty % 10u));
            s_item_label_storage[s_item_count][7] = '\0';
            s_item_labels[s_item_count] = s_item_label_storage[s_item_count];
            s_item_id_map[s_item_count] = i;
            s_item_count++;
        }
    }
#endif
    n = (s_item_count == 0u) ? 1u : s_item_count;
    if (s_item_count == 0u) {
        s_item_label_storage[0][0] = 'B'; s_item_label_storage[0][1] = 'A';
        s_item_label_storage[0][2] = 'C'; s_item_label_storage[0][3] = 'K';
        s_item_label_storage[0][4] = '\0';
        s_item_labels[0] = s_item_label_storage[0];
        s_item_id_map[0] = 0xFFu;
    }
    ngpc_menu_init(&s_item_menu, s_item_labels, n, 1u);
}

/* ============================================================ */
/* Anim trigger : enter BV_ANIM for ANIM_TICKS frames            */
/* ============================================================ */

static void be_start_anim(u8 actor, u8 hit)
{
    s_battle_view = BV_ANIM;
    s_anim_timer  = BE_ANIM_TICKS;
    s_anim_actor  = actor;
    s_anim_hit    = hit;
    s_hero_dx = s_hero_dy = s_enemy_dx = s_enemy_dy = 0;
}

/* ============================================================ */
/* DIALOG entry : queue result lines and switch to BV_DIALOG     */
/* ============================================================ */

static void be_open_result(u8 post_action)
{
    s_dialog_post = post_action;
    s_battle_view = BV_DIALOG;
    be_result_render();
}

/* ============================================================ */
/* Combat actions                                                */
/* ============================================================ */

static void be_enemy_turn(void)
{
    u8 raw, dmg, def;
    u8 crit = 0u;
    const NgpcMonster *m = &g_monster_table[s_monster_idx];
    const char *enemy_short = g_monster_names[s_monster_idx];

    be_result_clear();

    if (be_rand_pct() < m->miss_chance_pct) {
        be_result_push_damage(enemy_short, "MISS", 0u, 0u);
        be_play_sfx(BE_SFX_ENEMY_ATTACK);
        be_start_anim(BE_ANIM_ENEMY, 0u);
        s_dialog_post = POST_RETURN_CMD;
        return;
    }

    raw = be_rand_in_range(m->attack_min, m->attack_range);
    if (be_rand_pct() < m->crit_chance_pct) {
        u16 boosted = (u16)raw * (u16)m->crit_multiplier_x10 / 10u;
        raw = (u8)((boosted > 255u) ? 255u : boosted);
        crit = 1u;
    }
    def = BE_HERO_DEFENSE;
    dmg = be_sub_floor0(raw, def);
    if (dmg == 0u) dmg = 1u;
    if (s_guard_active) {
        dmg = be_sub_floor0(dmg, BE_GUARD_REDUCTION);
    }
    s_guard_active = 0u;

    be_play_sfx(BE_SFX_ENEMY_ATTACK);
    be_result_push_damage(enemy_short, "HIT", dmg, crit);

    if (dmg >= s_player_hp) {
        s_player_hp = 0u;
        be_play_sfx(BE_SFX_PLAYER_DEFEATED);
        be_emit(BE_ON_DEFEAT_EVENT);
        be_result_push("HERO KO");
        s_dialog_post = POST_END_LOSE;
    } else {
        s_player_hp = (u8)(s_player_hp - dmg);
        s_dialog_post = POST_RETURN_CMD;
    }
    s_stats_dirty = 1u;
    be_start_anim(BE_ANIM_ENEMY, 1u);
}

static void be_grant_rewards(void)
{
    const NgpcMonster *m = &g_monster_table[s_monster_idx];
    if (BE_XP_VAR_INDEX != 0xFFu)
        be_grant_var(BE_XP_VAR_INDEX, m->xp_drop, BE_XP_OVERFLOW_CLAMP);
    if (BE_GOLD_VAR_INDEX != 0xFFu)
        be_grant_var(BE_GOLD_VAR_INDEX, m->gold_drop, BE_GOLD_OVERFLOW_CLAMP);
#if defined(MONSTER_DROP_COUNT)
#if MONSTER_DROP_COUNT > 0u
    {
        u8 off  = g_monster_drop_offsets[s_monster_idx];
        u8 next = g_monster_drop_offsets[(u16)s_monster_idx + 1u];
        u8 k;
        for (k = off; k < next; k++) {
            if (be_rand_pct() < g_monster_drops[k].chance_pct) {
                ngpc_inv_add(&s_inventory, g_monster_drops[k].item_id, 1u);
            }
        }
    }
#endif
#endif
}

static void be_use_item(u8 item_idx)
{
#if ITEM_COUNT > 0u
    const NgpcItem *it;
    u8 qty;
    u8 amount;
    u16 new_hp;

    be_result_clear();
    if (item_idx == 0xFFu) {
        s_battle_view = BV_COMMAND;
        return;
    }
    qty = ngpc_inv_has(&s_inventory, item_idx);
    if (qty == 0u) {
        be_result_push("NO ITEM LEFT");
        be_open_result(POST_RETURN_ITEM);
        return;
    }
    it = &g_item_table[item_idx];
    amount = it->value;

    switch (it->type) {
    case ITEM_HEAL:
        if (s_player_hp >= BE_HERO_MAX_HP) {
            be_result_push("HP FULL");
            be_open_result(POST_RETURN_ITEM);
            return;
        }
        new_hp = (u16)s_player_hp + (u16)amount;
        s_player_hp = (new_hp > (u16)BE_HERO_MAX_HP) ? (u8)BE_HERO_MAX_HP : (u8)new_hp;
        be_result_push_damage("HERO", "HEAL", amount, 0u);
        break;
    case ITEM_DEF_UP:
        s_guard_active = 1u;
        be_result_push("HERO DEF UP");
        break;
    case ITEM_DICE_PLUS:
        if (amount >= s_enemy_hp) { s_enemy_hp = 0u; } else { s_enemy_hp = (u8)(s_enemy_hp - amount); }
        be_result_push_damage("HERO", "BOMB", amount, 0u);
        break;
    default: break;
    }

    if ((it->flags & ITEM_FLAG_CONSUMABLE) != 0u) {
        ngpc_inv_remove(&s_inventory, item_idx, 1u);
    }
    be_play_sfx(BE_SFX_ITEM_USE);
    s_stats_dirty = 1u;

    if (s_enemy_hp == 0u) {
        be_play_sfx(BE_SFX_ENEMY_DEFEATED);
        be_emit(BE_ON_VICTORY_EVENT);
        be_grant_rewards();
        be_result_push(g_monster_names[s_monster_idx]);
        be_result_push("KO");
        be_open_result(POST_END_WIN);
    } else {
        be_open_result(POST_ENEMY_TURN);
    }
#else
    (void)item_idx;
    s_battle_view = BV_COMMAND;
#endif
}

static void be_handle_command(u8 sel)
{
    u8 dmg;
    u8 def;
    u8 raw;
    u8 crit = 0u;
    const NgpcMonster *m = &g_monster_table[s_monster_idx];

    switch (sel) {
    case 0u:  /* FIGHT / ATTACK */
        be_result_clear();
        if (be_rand_pct() < BE_HERO_MISS_PCT) {
            be_result_push_damage("HERO", "MISS", 0u, 0u);
            be_play_sfx(BE_SFX_PLAYER_ATTACK);
            be_start_anim(BE_ANIM_PLAYER, 0u);
            s_dialog_post = POST_ENEMY_TURN;
            return;
        }
        raw = be_rand_in_range(BE_HERO_ATK_MIN, BE_HERO_ATK_RANGE);
        if (be_rand_pct() < BE_HERO_CRIT_PCT) {
            u16 boosted = (u16)raw * (u16)BE_HERO_CRIT_MULT_X10 / 10u;
            raw = (u8)((boosted > 255u) ? 255u : boosted);
            crit = 1u;
        }
        def = m->defense;
        dmg = be_sub_floor0(raw, def);
        if (dmg == 0u) dmg = 1u;
        be_play_sfx(BE_SFX_PLAYER_ATTACK);
        be_result_push_damage("HERO", "ATK", dmg, crit);
        if (dmg >= s_enemy_hp) {
            s_enemy_hp = 0u;
            be_play_sfx(BE_SFX_ENEMY_DEFEATED);
            be_emit(BE_ON_VICTORY_EVENT);
            be_grant_rewards();
            be_result_push(g_monster_names[s_monster_idx]);
            be_result_push("KO");
            s_dialog_post = POST_END_WIN;
        } else {
            s_enemy_hp = (u8)(s_enemy_hp - dmg);
            s_dialog_post = POST_ENEMY_TURN;
        }
        s_stats_dirty = 1u;
        be_start_anim(BE_ANIM_PLAYER, 1u);
        break;

    case 1u:  /* ITEM */
        be_build_item_menu();
        s_battle_view = BV_ITEM;
        break;

    case 2u:  /* GUARD */
        be_result_clear();
        s_guard_active = 1u;
        be_play_sfx(BE_SFX_GUARD);
        be_result_push("HERO GUARDS");
        be_open_result(POST_ENEMY_TURN);
        break;

    default:  /* RUN */
        be_result_clear();
        if (be_rand_pct() < BE_RUN_SUCCESS_PCT) {
            be_result_push("HERO RUNS");
            be_open_result(POST_END_RUN);
        } else {
            be_result_push("CANT ESCAPE");
            be_open_result(POST_ENEMY_TURN);
        }
        break;
    }
}

/* ============================================================ */
/* Restore the menu labels after DIALOG / RESULT rows wrote      */
/* over them.                                                    */
/* ============================================================ */

static void be_restore_menu_labels(void)
{
    u8 i;
    for (i = 14u; i < 18u; i++) be_clear_row(i);
    for (i = 0u; i < 4u; i++) {
        if (s_cmd_enabled[i]) {
            ngpc_text_print(BE_HUD_PLANE, BE_HUD_PAL,
                            BE_CMD_COL[i], BE_CMD_ROW[i], BE_CMD_LABEL[i]);
        }
    }
    s_menu_dirty = 1u;
    s_prev_cmd_sel = 0xFFu;
}

static void be_after_dialog(void)
{
    u8 post = s_dialog_post;
    s_dialog_post = POST_NONE;
    switch (post) {
    case POST_RETURN_CMD:
        s_battle_view = BV_COMMAND;
        be_restore_menu_labels();
        break;
    case POST_RETURN_ITEM:
        s_battle_view = BV_ITEM;
        break;
    case POST_ENEMY_TURN:
        be_enemy_turn();  /* may set BV_ANIM or BV_DIALOG */
        break;
    case POST_END_WIN:
    case POST_END_LOSE:
    case POST_END_RUN:
        s_active = 0u;
        s_battle_view = BV_OFF;
        if (BE_BGM_VICTORY != 0u && post == POST_END_WIN)
            battle_engine_play_bgm(BE_BGM_VICTORY);
        else if (BE_BGM_DEFEAT != 0u && post == POST_END_LOSE)
            battle_engine_play_bgm(BE_BGM_DEFEAT);
        break;
    default:
        s_battle_view = BV_COMMAND;
        be_restore_menu_labels();
        break;
    }
}

/* ============================================================ */
/* Cursor : clear all 4 cursor cells, draw at current selection  */
/* ============================================================ */

static void be_render_cursor(void)
{
    char cur[2];
    u8 i;
    cur[0] = ' '; cur[1] = '\0';
    for (i = 0u; i < 4u; i++) {
        if (s_cmd_enabled[i])
            ngpc_text_print(BE_HUD_PLANE, BE_HUD_PAL,
                            BE_CUR_COL[i], BE_CUR_ROW[i], cur);
    }
    cur[0] = (char)BE_CURSOR_CHAR;
    ngpc_text_print(BE_HUD_PLANE, BE_HUD_PAL,
                    BE_CUR_COL[s_cmd_sel], BE_CUR_ROW[s_cmd_sel], cur);
    s_prev_cmd_sel = s_cmd_sel;
    s_menu_dirty = 0u;
}

/* Move cursor in 2x2 grid, skip disabled cells. */
static u8 be_cmd_grid_step(u8 cur, u8 dir)
{
    u8 tries;
    u8 next = cur;
    /* dir: 0=LEFT, 1=RIGHT, 2=UP, 3=DOWN. LEFT/RIGHT flip col bit;
     * UP/DOWN flip row bit. Same as demo XOR navigation.        */
    for (tries = 0u; tries < 4u; tries++) {
        if (dir < 2u) next = (u8)(next ^ 1u);
        else          next = (u8)(next ^ 2u);
        if (s_cmd_enabled[next]) return next;
    }
    return cur;
}

/* ============================================================ */
/* Stats redraw (only when HP changes)                           */
/* ============================================================ */

static void be_render_stats_if_dirty(void)
{
    const NgpcMonster *m;
    if (!s_stats_dirty &&
        s_prev_player_hp == s_player_hp &&
        s_prev_enemy_hp  == s_enemy_hp) return;

    m = &g_monster_table[s_monster_idx];

#if BE_SHOW_ENEMY_HP_VALUE
    be_print_ratio_line(1u, 3u, "HP", (u16)s_enemy_hp, (u16)m->max_hp);
#else
    be_print_ratio_line(1u, 3u, "HP", 0u, 0u);
#endif
#if BE_SHOW_HERO_HP_VALUE
    be_print_ratio_line(9u, 10u, "HP", (u16)s_player_hp, (u16)BE_HERO_MAX_HP);
#endif
    s_prev_player_hp = s_player_hp;
    s_prev_enemy_hp  = s_enemy_hp;
    s_stats_dirty = 0u;
}

/* ============================================================ */
/* Layout (called ONCE on battle entry)                          */
/* ============================================================ */

static void be_layout(void)
{
    u8 i;

    ngpc_gfx_set_viewport(0u, 0u, 160u, 152u);
    ngpc_gfx_set_bg_color(BE_RGB(0, 0, 0));
    HW_SCR_PRIO = 0x00u;  /* SCR1 in front (HUD), SCR2 behind (BG) */
    ngpc_gfx_scroll(GFX_SCR1, 0, 0);
    ngpc_gfx_scroll(GFX_SCR2, 0, 0);
    ngpc_gfx_clear(GFX_SCR1);
    ngpc_gfx_clear(GFX_SCR2);
    ngpc_sprite_hide_all();

    battle_engine_load_bg();
    battle_engine_load_sprites();

    /* HUD palette : color 0 transparent (sprite/BG show through), 1 = white. */
    ngpc_gfx_set_palette(GFX_SCR1, BE_HUD_PAL,
        BE_RGB(0,  0,  0),
        BE_RGB(15, 15, 15),
        BE_RGB(10, 10, 10),
        BE_RGB( 5,  5,  5));

    /* Demo HUD :
     *   enemy NAME at (1, 1)
     *   enemy HP   at (1, 3)
     *   hero  NAME at (9, 8)
     *   hero  HP   at (9, 10)
     */
#if BE_SHOW_ENEMY_NAME
    be_print_name(1u, 1u, g_monster_names[s_monster_idx], 8u);
#else
    be_print_name(1u, 1u, "ENEMY", 8u);
#endif
    be_print_name(9u, 8u, "HERO", 8u);

    /* Pre-compute enabled cmd cells. */
    s_cmd_enabled[0] = (u8)BE_CMD_ATTACK_ENABLED;
    s_cmd_enabled[1] = (u8)BE_CMD_ITEM_ENABLED;
    s_cmd_enabled[2] = (u8)BE_CMD_GUARD_ENABLED;
    s_cmd_enabled[3] = (u8)BE_CMD_RUN_ENABLED;

    /* Menu labels (only enabled cells). */
    for (i = 0u; i < 4u; i++) {
        if (s_cmd_enabled[i]) {
            ngpc_text_print(BE_HUD_PLANE, BE_HUD_PAL,
                            BE_CMD_COL[i], BE_CMD_ROW[i], BE_CMD_LABEL[i]);
        }
    }

    /* Initial cursor on first enabled cell. */
    s_cmd_sel = 0u;
    while (s_cmd_sel < 4u && !s_cmd_enabled[s_cmd_sel]) s_cmd_sel++;
    if (s_cmd_sel >= 4u) s_cmd_sel = 0u;
    s_prev_cmd_sel = 0xFFu;

    /* Reset dirty flags & anim. */
    s_prev_player_hp = 0xFFu;
    s_prev_enemy_hp  = 0xFFu;
    s_stats_dirty = 1u;
    s_menu_dirty  = 1u;
    s_hero_dx = s_hero_dy = s_enemy_dx = s_enemy_dy = 0;
    s_anim_timer = 0u;
}

/* ============================================================ */
/* Public API                                                    */
/* ============================================================ */

void battle_engine_init(void)
{
    s_active = 0u;
    s_battle_view = BV_OFF;
    ngpc_qrandom_init();
    ngpc_inv_init(&s_inventory);
#if BE_STARTER_INVENTORY_COUNT > 0u
    {
        u8 i;
        for (i = 0u; i < BE_STARTER_INVENTORY_COUNT; i++) {
            ngpc_inv_add(&s_inventory, g_be_starter_inventory[i].item_id,
                                       g_be_starter_inventory[i].qty);
        }
    }
#endif
}

void battle_engine_enter(u8 monster_idx)
{
#if defined(MONSTER_COUNT)
#if MONSTER_COUNT > 0u
    if (monster_idx >= MONSTER_COUNT) monster_idx = 0u;
    s_monster_idx  = monster_idx;
    s_active       = 1u;
    s_battle_view  = BV_COMMAND;
    s_dialog_post  = POST_NONE;
    s_guard_active = 0u;
    s_player_hp    = BE_HERO_MAX_HP;
    s_enemy_hp     = g_monster_table[monster_idx].max_hp;
    be_layout();
    be_emit(BE_ON_BATTLE_START_EVENT);
    if (BE_BGM_BATTLE != 0u) battle_engine_play_bgm(BE_BGM_BATTLE);
#else
    (void)monster_idx;
#endif
#else
    (void)monster_idx;
#endif
}

u8 battle_engine_is_active(void) { return s_active; }

void battle_engine_update(void)
{
    u8 sel;
    if (!s_active) return;
    /* Autorun's input_update is AFTER our continue → must poll here. */
    ngpc_input_update();
    s_frame_counter++;

    /* ANIM : decrement timer, update offsets each frame, no input. */
    if (s_battle_view == BV_ANIM) {
        if (s_anim_timer > 0u) {
            /* thrust forward for the actor, shake for the target if hit. */
            s8 thrust = (s_anim_timer > (BE_ANIM_TICKS / 2u)) ? 6 : 3;
            s8 shake_x = (s_anim_timer & 1u) ? (s8)-2 : (s8)2;
            s8 shake_y = (s_anim_timer & 2u) ? (s8)-1 : (s8)1;
            s_hero_dx = s_hero_dy = s_enemy_dx = s_enemy_dy = 0;
            if (s_anim_actor == BE_ANIM_PLAYER) {
                s_hero_dx = thrust;
                if (s_anim_hit) { s_enemy_dx = shake_x; s_enemy_dy = shake_y; }
            } else {
                s_enemy_dx = (s8)(-thrust);
                if (s_anim_hit) { s_hero_dx = shake_x; s_hero_dy = shake_y; }
            }
            s_anim_timer--;
        }
        if (s_anim_timer == 0u) {
            /* Anim done : show the result lines and wait for A. */
            s_hero_dx = s_hero_dy = s_enemy_dx = s_enemy_dy = 0;
            s_battle_view = BV_DIALOG;
            be_result_render();
        }
        return;
    }

    if (s_battle_view == BV_DIALOG) {
        if (ngpc_pad_pressed & BE_INPUT_CONFIRM) be_after_dialog();
        return;
    }

    if (s_battle_view == BV_ITEM && (ngpc_pad_pressed & BE_INPUT_CANCEL)) {
        be_play_sfx(BE_SFX_MENU_CANCEL);
        s_battle_view = BV_COMMAND;
        s_menu_dirty = 1u;
        return;
    }
    if (s_battle_view == BV_ITEM) {
        sel = ngpc_menu_update(&s_item_menu);
        if (sel == MENU_NONE) return;
        be_play_sfx(BE_SFX_MENU_CONFIRM);
        if (s_item_count == 0u) {
            s_battle_view = BV_COMMAND;
            be_restore_menu_labels();
            return;
        }
        be_use_item(s_item_id_map[sel]);
        return;
    }

    /* COMMAND : 2x2 grid navigation */
    if (ngpc_pad_pressed & PAD_LEFT)        { s_cmd_sel = be_cmd_grid_step(s_cmd_sel, 0u); s_menu_dirty = 1u; be_play_sfx(BE_SFX_MENU_MOVE); }
    else if (ngpc_pad_pressed & PAD_RIGHT)  { s_cmd_sel = be_cmd_grid_step(s_cmd_sel, 1u); s_menu_dirty = 1u; be_play_sfx(BE_SFX_MENU_MOVE); }
    else if (ngpc_pad_pressed & PAD_UP)     { s_cmd_sel = be_cmd_grid_step(s_cmd_sel, 2u); s_menu_dirty = 1u; be_play_sfx(BE_SFX_MENU_MOVE); }
    else if (ngpc_pad_pressed & PAD_DOWN)   { s_cmd_sel = be_cmd_grid_step(s_cmd_sel, 3u); s_menu_dirty = 1u; be_play_sfx(BE_SFX_MENU_MOVE); }
    else if (ngpc_pad_pressed & BE_INPUT_CONFIRM) {
        be_play_sfx(BE_SFX_MENU_CONFIRM);
        be_handle_command(s_cmd_sel);
    }
}

void battle_engine_render(void)
{
    if (!s_active) return;
    ngpc_sprite_hide_all();

    /* Sprites with current knockback offsets (0,0 outside ANIM). */
    battle_engine_draw_hero(
        (s16)((s16)BE_ANCHOR_PLAYER_PORTRAIT_X + (s16)s_hero_dx),
        (s16)((s16)BE_ANCHOR_PLAYER_PORTRAIT_Y + (s16)s_hero_dy),
        (u16)(s_frame_counter / 20u));
    battle_engine_draw_monster(
        s_monster_idx,
        (s16)((s16)BE_ANCHOR_ENEMY_PORTRAIT_X + (s16)s_enemy_dx),
        (s16)((s16)BE_ANCHOR_ENEMY_PORTRAIT_Y + (s16)s_enemy_dy),
        (u16)(s_frame_counter / 14u));

    be_render_stats_if_dirty();
    if (s_battle_view == BV_COMMAND && (s_menu_dirty || s_prev_cmd_sel != s_cmd_sel)) {
        be_render_cursor();
    }

    /* Flush the sprite shadow buffer to HW. The autorun normally calls this
     * at the end of its main loop, but we use `continue` to take over the
     * frame and skip that call — without our own flush here, palette + tile
     * changes from ngpc_mspr_draw stay buffered and the user sees the
     * GAMEPLAY palette indices instead of our new battle slots (e.g. slot 10
     * not committed → sprite reads the stale gameplay palette 0).          */
    ngpc_sprite_frame_end();
}
