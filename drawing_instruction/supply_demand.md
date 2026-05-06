// This work is licensed under Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International  
// https://creativecommons.org/licenses/by-nc-sa/4.0/
// © BigBeluga


//@version=6
indicator("Supply and Demand Zones [BigBeluga]", overlay = true)


// ＩＮＰＵＴＳ ――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――{
col_supply = input.color(color.orange, "Supply")
col_demand = input.color(#009fd4, "Demand")

var vol        = array.new<float>()
var bear_boxes = array.new<box>()
var bull_boxes = array.new<box>()
var BullDelta  = array.new<float>()
var BearDelta  = array.new<float>()

var count_bear = 0
var count_bull = 0
// }


// ＣＡＬＣＵＬＡＴＩＯＮＳ――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――{
vol.push(volume)

if vol.size() > 1000
    vol.shift()


extra_vol = volume > vol.avg()
atr = ta.atr(200)*2
bear_candle = close < open 
bull_candle = close > open


if bear_candle and bear_candle[1] and bear_candle[2] and  extra_vol[1] and count_bear == 0

    delta = 0.

    for i = 0 to 5
        
        if bull_candle[i]
            count_bear := 1
            bear_boxes.push(box.new(bar_index-i, low[i]+atr, bar_index, low[i], bgcolor = color(na), border_color = col_supply, border_width = 2, text = "Supply: " + str.tostring(delta, format.volume), text_halign = text.align_right, text_size = size.normal))
            BearDelta.push(delta)
            break
        delta += bear_candle[i] ? -volume[i] : volume[i]
        

if count_bear >= 1
    count_bear += 1

if count_bear >= 15
    count_bear:= 0



if bull_candle and bull_candle[1] and bull_candle[2] and  extra_vol[1] and count_bull == 0

    delta = 0.

    for i = 0 to 5
        if bear_candle[i]
            count_bull := 1
            bull_boxes.push(box.new(bar_index-i, high[i], bar_index, high[i]-atr, bgcolor = color(na), border_color = col_demand, border_width = 2, text = "Demand: " + str.tostring(delta, format.volume), text_halign = text.align_right, text_size = size.normal))
            BullDelta.push(delta)
            break
        delta += bull_candle[i] ? volume[i] : -volume[i]

if count_bull >= 1
    count_bull += 1

if count_bull >= 15
    count_bull:= 0



for b in bear_boxes

    i = bear_boxes.indexof(b)

    buy = 0.
    sell = 0.


    for bb in BullDelta
        buy += math.abs(bb)
    for ss in BearDelta
        sell += math.abs(ss)

    tot = buy + sell


    b.set_text("Supply: " + str.tostring(BearDelta.get(i), format.volume) + " | " + str.tostring(math.abs(BearDelta.get(i) / tot * 100), format.percent))


    b.set_right(bar_index+100)
    b.set_extend(extend.right)
    top = b.get_top()
    bot = b.get_bottom()
    b.set_bgcolor(color.new(col_supply, 90))

    if close > top 
        b.delete()

        bear_boxes.remove(bear_boxes.indexof(b))
        BearDelta.remove(bear_boxes.indexof(b))

    if (b.get_right() - b.get_left()-15) > 20
        if high > bot and low < bot 
            b.set_border_style(line.style_dashed)
            b.set_border_width(1)

if bear_boxes.size() > 0
    for i = 0 to bear_boxes.size() - 1
        lvl = bear_boxes.get(i)
        top = lvl.get_top()
        bot = lvl.get_bottom()

        for j = 0 to bear_boxes.size() - 1
            if i == j
                continue  // Don't compare with self

            l   = bear_boxes.get(j)

            top1 = l.get_top()
            bot1 = l.get_bottom()

            if top1 < top and top1 > bot
                lvl.delete()
                bear_boxes.remove(bear_boxes.indexof(lvl))
                BearDelta.remove(bear_boxes.indexof(lvl))


if bear_boxes.size()> 5 
    bear_boxes.shift().delete()
    BearDelta.shift()



for b in  bull_boxes

    i = bull_boxes.indexof(b)

    buy = 0.
    sell = 0.

    for bb in BullDelta
        buy += math.abs(bb)
    for ss in BearDelta
        sell += math.abs(ss)

    tot = buy + sell

    b.set_text("Demand: " + str.tostring(BullDelta.get(i), format.volume) + " | " + str.tostring(BullDelta.get(i) / tot * 100, format.percent))


    b.set_right(bar_index+100)
    b.set_extend(extend.right)
    bot = b.get_bottom()
    top = b.get_top()
    b.set_bgcolor(color.new(col_demand, 90))

    if close < bot 
        b.delete()

        bull_boxes.remove(bull_boxes.indexof(b))
        BullDelta.remove(bull_boxes.indexof(b))

    if (b.get_right() - b.get_left()-15) > 20
        if low < top and high > top 
            b.set_border_style(line.style_dashed)
            b.set_border_width(1)


if bull_boxes.size() > 0
    for i = 0 to bull_boxes.size() - 1
        lvl = bull_boxes.get(i)
        top = lvl.get_top()
        bot = lvl.get_bottom()

        for j = 0 to bull_boxes.size() - 1
            if i == j
                continue  

            l   = bull_boxes.get(j)

            top1 = l.get_top()
            bot1 = l.get_bottom()

            if bot1 < top and bot1 > bot
                lvl.delete()
                bull_boxes.remove(bull_boxes.indexof(lvl))
                BullDelta.remove(bull_boxes.indexof(lvl))


if bull_boxes.size()> 5 
    bull_boxes.shift().delete() 
    BullDelta.shift()



var dash = table.new(position.bottom_right, 10, 10, chart.bg_color)
if barstate.islast

    dash.cell(0, 0, "Total Supply:", text_halign = text.align_left, text_color = col_supply)
    dash.cell(0, 1, "Total Demand:", text_halign = text.align_left, text_color = col_demand)

    dash.cell(1, 0, str.tostring(BearDelta.sum()), text_color = col_supply)
    dash.cell(1, 1, str.tostring(BullDelta.sum()), text_color = col_demand)


// }