// This Pine Script® code is subject to the terms of the Mozilla Public License 2.0 at https://mozilla.org/MPL/2.0/
// © Uncle_the_shooter

//@version=6
indicator('Multi Length Market Structure (BoS + ChoCh)', overlay = true, max_lines_count = 500, max_labels_count = 500)

// Input parameters for pivot lengths and colors
pivot_length_1 = input.int(5, title = 'Pivot Length 1', minval = 1)
bos_up_color_1 = input.color(color.green, title = 'BoS Up and Pivot High 1 Color')
bos_down_color_1 = input.color(color.red, title = 'BoS Down and Pivot Low 1 Color')
pivot_length_2 = input.int(10, title = 'Pivot Length 2', minval = 1)
bos_up_color_2 = input.color(color.green, title = 'BoS Up and Pivot High 2 Color')
bos_down_color_2 = input.color(color.red, title = 'BoS Down and Pivot Low 2 Color')
pivot_length_3 = input.int(15, title = 'Pivot Length 3', minval = 1)
bos_up_color_3 = input.color(color.green, title = 'BoS Up and Pivot High 3 Color')
bos_down_color_3 = input.color(color.red, title = 'BoS Down and Pivot Low 3 Color')
pivot_length_4 = input.int(20, title = 'Pivot Length 4', minval = 1)
bos_up_color_4 = input.color(color.green, title = 'BoS Up and Pivot High 4 Color')
bos_down_color_4 = input.color(color.red, title = 'BoS Down and Pivot Low 4 Color')
pivot_length_5 = input.int(30, title = 'Pivot Length 5', minval = 1)
bos_up_color_5 = input.color(color.green, title = 'BoS Up and Pivot High 5 Color')
bos_down_color_5 = input.color(color.red, title = 'BoS Down and Pivot Low 5 Color')
pivot_length_6 = input.int(50, title = 'Pivot Length 6', minval = 1)
bos_up_color_6 = input.color(color.green, title = 'BoS Up and Pivot High 6 Color')
bos_down_color_6 = input.color(color.red, title = 'BoS Down and Pivot Low 6 Color')
show_bos = input.bool(true, title = 'Show BoS (labels, lines, triangles)', group = 'BoS / ChoCh Visibility')
show_choch = input.bool(true, title = 'Show ChoCh (labels, lines, triangles)', group = 'BoS / ChoCh Visibility')

// Unbroken Pivot Lines 
show_unbroken_only = input.bool(false, title = 'Show Only Unbroken Pivot Lines', group = 'Unbroken Pivot Lines')
unbroken_transparency = input.int(70, title = 'Unbroken Lines Transparency', minval = 0, maxval = 100, group = 'Unbroken Pivot Lines')
unbroken_style = input.string(line.style_solid, title = 'Unbroken Lines Style', options = [line.style_solid, line.style_dashed, line.style_dotted], group = 'Unbroken Pivot Lines')

// Pivot label settings
show_labels = input.bool(true, title = 'Show HH/HL/LH/LL Labels')
show_labels_pivot = input.string('Pivot 1', title = 'Show Labels for Pivot', options = ['None', 'Pivot 1', 'Pivot 2', 'Pivot 3', 'Pivot 4', 'Pivot 5', 'Pivot 6'])
text_color = input.color(color.gray, title = 'Text Color for Pivot and BoS/ChoCh Labels')

// Automatic label offset
offset_multiplier = 0.2
offset_value = ta.atr(14) * offset_multiplier
high_label_offset = offset_value
low_label_offset = offset_value
bos_label_offset = offset_value * 0.1

// Global arrays for each pivot
var array<float> broken_highs_1 = array.new_float(0)
var array<float> broken_lows_1 = array.new_float(0)
var array<line> high_bos_lines_1 = array.new_line(0)
var array<line> low_bos_lines_1 = array.new_line(0)
var array<float> broken_highs_2 = array.new_float(0)
var array<float> broken_lows_2 = array.new_float(0)
var array<line> high_bos_lines_2 = array.new_line(0)
var array<line> low_bos_lines_2 = array.new_line(0)
var array<float> broken_highs_3 = array.new_float(0)
var array<float> broken_lows_3 = array.new_float(0)
var array<line> high_bos_lines_3 = array.new_line(0)
var array<line> low_bos_lines_3 = array.new_line(0)
var array<float> broken_highs_4 = array.new_float(0)
var array<float> broken_lows_4 = array.new_float(0)
var array<line> high_bos_lines_4 = array.new_line(0)
var array<line> low_bos_lines_4 = array.new_line(0)
var array<float> broken_highs_5 = array.new_float(0)
var array<float> broken_lows_5 = array.new_float(0)
var array<line> high_bos_lines_5 = array.new_line(0)
var array<line> low_bos_lines_5 = array.new_line(0)
var array<float> broken_highs_6 = array.new_float(0)
var array<float> broken_lows_6 = array.new_float(0)
var array<line> high_bos_lines_6 = array.new_line(0)
var array<line> low_bos_lines_6 = array.new_line(0)

// Arrays for unbroken pivot lines
var array<line> unbroken_high_lines = array.new_line()
var array<float> unbroken_high_prices = array.new_float()
var array<color> unbroken_high_colors = array.new_color()
var array<line> unbroken_low_lines = array.new_line()
var array<float> unbroken_low_prices = array.new_float()
var array<color> unbroken_low_colors = array.new_color()

// Arrays to collect BoS/ChoCh events for each bar
var array<int> bos_up_lengths = array.new_int(0)
var array<float> bos_up_prices = array.new_float(0)
var array<int> bos_up_bars = array.new_int(0)
var array<int> bos_up_dirs = array.new_int(0)
var array<color> bos_up_colors = array.new_color(0)
var array<int> bos_down_lengths = array.new_int(0)
var array<float> bos_down_prices = array.new_float(0)
var array<int> bos_down_bars = array.new_int(0)
var array<int> bos_down_dirs = array.new_int(0)
var array<color> bos_down_colors = array.new_color(0)

// Global variables to track the last breakout direction for each pivot
var int last_breakout_dir_1 = 0
var int last_breakout_dir_2 = 0
var int last_breakout_dir_3 = 0
var int last_breakout_dir_4 = 0
var int last_breakout_dir_5 = 0
var int last_breakout_dir_6 = 0

// f_processPivot Function 
f_processPivot(length, bos_color_up, bos_color_down, text_color, show_labels_this, high_offset, low_offset, broken_highs, broken_lows, high_bos_lines, low_bos_lines, previous_dir) =>
    pivot_high = ta.pivothigh(high, length, length)
    pivot_low = ta.pivotlow(low, length, length)
   
    var float last_high = na
    var int last_high_bar = na
    var float last_low = na
    var int last_low_bar = na
    var float prev_high = na
    var float prev_low = na

    if not na(pivot_high)
        last_high := pivot_high
        last_high_bar := bar_index[length]
        label_type = not na(prev_high) ? pivot_high > prev_high ? 'HH' : 'LH' : 'HH'
        prev_high := pivot_high
        if show_labels_this
            label.new(last_high_bar, pivot_high + high_offset, label_type, style = label.style_label_down, color = color.new(color.white, 100), textcolor = text_color, size = size.small)
        
        if show_unbroken_only and not array.includes(broken_highs, pivot_high) and not array.includes(unbroken_high_prices, pivot_high) and close <= pivot_high
            l = line.new(last_high_bar, pivot_high, bar_index + 500, pivot_high, extend = extend.right, color = color.new(bos_color_up, unbroken_transparency), style = unbroken_style, width = 2)
            array.push(unbroken_high_lines, l)
            array.push(unbroken_high_prices, pivot_high)
            array.push(unbroken_high_colors, bos_color_up)

    if not na(pivot_low)
        last_low := pivot_low
        last_low_bar := bar_index[length]
        label_type = not na(prev_low) ? pivot_low > prev_low ? 'HL' : 'LL' : 'HL'
        prev_low := pivot_low
        if show_labels_this
            label.new(last_low_bar, pivot_low - low_offset, label_type, style = label.style_label_up, color = color.new(color.white, 100), textcolor = text_color, size = size.small)
        
        if show_unbroken_only and not array.includes(broken_lows, pivot_low) and not array.includes(unbroken_low_prices, pivot_low) and close >= pivot_low
            l = line.new(last_low_bar, pivot_low, bar_index + 500, pivot_low, extend = extend.right, color = color.new(bos_color_down, unbroken_transparency), style = unbroken_style, width = 2)
            array.push(unbroken_low_lines, l)
            array.push(unbroken_low_prices, pivot_low)
            array.push(unbroken_low_colors, bos_color_down)

    bool bos_up = false
    bool bos_down = false
    int new_breakout_dir = 0
    if not na(last_high)
        crossover_val = ta.crossover(close, last_high)
        bos_up := crossover_val and not array.includes(broken_highs, last_high)
    if not na(last_low)
        crossunder_val = ta.crossunder(close, last_low)
        bos_down := crossunder_val and not array.includes(broken_lows, last_low)

    float broken_high = na
    int broken_high_bar = na
    float broken_low = na
    int broken_low_bar = na

    if bos_up
        is_choch = previous_dir == -1
        array.push(broken_highs, last_high)
        if (is_choch and show_choch) or (not is_choch and show_bos)
            l = line.new(last_high_bar, last_high, bar_index, last_high, color = bos_color_up)
            array.push(high_bos_lines, l)
        broken_high := last_high
        broken_high_bar := last_high_bar
        new_breakout_dir := 1

    if bos_down
        is_choch = previous_dir == 1
        array.push(broken_lows, last_low)
        if (is_choch and show_choch) or (not is_choch and show_bos)
            l = line.new(last_low_bar, last_low, bar_index, last_low, color = bos_color_down)
            array.push(low_bos_lines, l)
        broken_low := last_low
        broken_low_bar := last_low_bar
        new_breakout_dir := -1

    [bos_up, bos_down, new_breakout_dir, broken_high, broken_high_bar, broken_low, broken_low_bar]

// Call function for each pivot
[bos_up_1, bos_down_1, new_breakout_dir_1, broken_high_1, broken_high_bar_1, broken_low_1, broken_low_bar_1] = f_processPivot(pivot_length_1, bos_up_color_1, bos_down_color_1, text_color, show_labels and show_labels_pivot == 'Pivot 1', high_label_offset, low_label_offset, broken_highs_1, broken_lows_1, high_bos_lines_1, low_bos_lines_1, last_breakout_dir_1)
[bos_up_2, bos_down_2, new_breakout_dir_2, broken_high_2, broken_high_bar_2, broken_low_2, broken_low_bar_2] = f_processPivot(pivot_length_2, bos_up_color_2, bos_down_color_2, text_color, show_labels and show_labels_pivot == 'Pivot 2', high_label_offset, low_label_offset, broken_highs_2, broken_lows_2, high_bos_lines_2, low_bos_lines_2, last_breakout_dir_2)
[bos_up_3, bos_down_3, new_breakout_dir_3, broken_high_3, broken_high_bar_3, broken_low_3, broken_low_bar_3] = f_processPivot(pivot_length_3, bos_up_color_3, bos_down_color_3, text_color, show_labels and show_labels_pivot == 'Pivot 3', high_label_offset, low_label_offset, broken_highs_3, broken_lows_3, high_bos_lines_3, low_bos_lines_3, last_breakout_dir_3)
[bos_up_4, bos_down_4, new_breakout_dir_4, broken_high_4, broken_high_bar_4, broken_low_4, broken_low_bar_4] = f_processPivot(pivot_length_4, bos_up_color_4, bos_down_color_4, text_color, show_labels and show_labels_pivot == 'Pivot 4', high_label_offset, low_label_offset, broken_highs_4, broken_lows_4, high_bos_lines_4, low_bos_lines_4, last_breakout_dir_4)
[bos_up_5, bos_down_5, new_breakout_dir_5, broken_high_5, broken_high_bar_5, broken_low_5, broken_low_bar_5] = f_processPivot(pivot_length_5, bos_up_color_5, bos_down_color_5, text_color, show_labels and show_labels_pivot == 'Pivot 5', high_label_offset, low_label_offset, broken_highs_5, broken_lows_5, high_bos_lines_5, low_bos_lines_5, last_breakout_dir_5)
[bos_up_6, bos_down_6, new_breakout_dir_6, broken_high_6, broken_high_bar_6, broken_low_6, broken_low_bar_6] = f_processPivot(pivot_length_6, bos_up_color_6, bos_down_color_6, text_color, show_labels and show_labels_pivot == 'Pivot 6', high_label_offset, low_label_offset, broken_highs_6, broken_lows_6, high_bos_lines_6, low_bos_lines_6, last_breakout_dir_6)

// Update global breakout direction variables
last_breakout_dir_1 := bos_up_1 or bos_down_1 ? new_breakout_dir_1 : last_breakout_dir_1
last_breakout_dir_2 := bos_up_2 or bos_down_2 ? new_breakout_dir_2 : last_breakout_dir_2
last_breakout_dir_3 := bos_up_3 or bos_down_3 ? new_breakout_dir_3 : last_breakout_dir_3
last_breakout_dir_4 := bos_up_4 or bos_down_4 ? new_breakout_dir_4 : last_breakout_dir_4
last_breakout_dir_5 := bos_up_5 or bos_down_5 ? new_breakout_dir_5 : last_breakout_dir_5
last_breakout_dir_6 := bos_up_6 or bos_down_6 ? new_breakout_dir_6 : last_breakout_dir_6

// Unbroken Pivot Lines - optional feature
if show_unbroken_only
    if array.size(unbroken_high_lines) > 0
        for i = array.size(unbroken_high_lines) - 1 to 0
            if close > array.get(unbroken_high_prices, i)
                line.delete(array.get(unbroken_high_lines, i))
                array.remove(unbroken_high_lines, i)
                array.remove(unbroken_high_prices, i)
                array.remove(unbroken_high_colors, i)
    
    if array.size(unbroken_low_lines) > 0
        for i = array.size(unbroken_low_lines) - 1 to 0
            if close < array.get(unbroken_low_prices, i)
                line.delete(array.get(unbroken_low_lines, i))
                array.remove(unbroken_low_lines, i)
                array.remove(unbroken_low_prices, i)
                array.remove(unbroken_low_colors, i)


array.clear(bos_up_lengths)
array.clear(bos_up_prices)
array.clear(bos_up_bars)
array.clear(bos_up_dirs)
array.clear(bos_up_colors)
array.clear(bos_down_lengths)
array.clear(bos_down_prices)
array.clear(bos_down_bars)
array.clear(bos_down_dirs)
array.clear(bos_down_colors)

// Collect upward events only if visible
if bos_up_1 and ((last_breakout_dir_1[1] == -1 and show_choch) or (last_breakout_dir_1[1] != -1 and show_bos))
    array.push(bos_up_lengths, pivot_length_1)
    array.push(bos_up_prices, broken_high_1)
    array.push(bos_up_bars, broken_high_bar_1)
    array.push(bos_up_dirs, last_breakout_dir_1[1])
    array.push(bos_up_colors, bos_up_color_1)
if bos_up_2 and ((last_breakout_dir_2[1] == -1 and show_choch) or (last_breakout_dir_2[1] != -1 and show_bos))
    array.push(bos_up_lengths, pivot_length_2)
    array.push(bos_up_prices, broken_high_2)
    array.push(bos_up_bars, broken_high_bar_2)
    array.push(bos_up_dirs, last_breakout_dir_2[1])
    array.push(bos_up_colors, bos_up_color_2)
if bos_up_3 and ((last_breakout_dir_3[1] == -1 and show_choch) or (last_breakout_dir_3[1] != -1 and show_bos))
    array.push(bos_up_lengths, pivot_length_3)
    array.push(bos_up_prices, broken_high_3)
    array.push(bos_up_bars, broken_high_bar_3)
    array.push(bos_up_dirs, last_breakout_dir_3[1])
    array.push(bos_up_colors, bos_up_color_3)
if bos_up_4 and ((last_breakout_dir_4[1] == -1 and show_choch) or (last_breakout_dir_4[1] != -1 and show_bos))
    array.push(bos_up_lengths, pivot_length_4)
    array.push(bos_up_prices, broken_high_4)
    array.push(bos_up_bars, broken_high_bar_4)
    array.push(bos_up_dirs, last_breakout_dir_4[1])
    array.push(bos_up_colors, bos_up_color_4)
if bos_up_5 and ((last_breakout_dir_5[1] == -1 and show_choch) or (last_breakout_dir_5[1] != -1 and show_bos))
    array.push(bos_up_lengths, pivot_length_5)
    array.push(bos_up_prices, broken_high_5)
    array.push(bos_up_bars, broken_high_bar_5)
    array.push(bos_up_dirs, last_breakout_dir_5[1])
    array.push(bos_up_colors, bos_up_color_5)
if bos_up_6 and ((last_breakout_dir_6[1] == -1 and show_choch) or (last_breakout_dir_6[1] != -1 and show_bos))
    array.push(bos_up_lengths, pivot_length_6)
    array.push(bos_up_prices, broken_high_6)
    array.push(bos_up_bars, broken_high_bar_6)
    array.push(bos_up_dirs, last_breakout_dir_6[1])
    array.push(bos_up_colors, bos_up_color_6)

// Collect downward events only if visible
if bos_down_1 and ((last_breakout_dir_1[1] == 1 and show_choch) or (last_breakout_dir_1[1] != 1 and show_bos))
    array.push(bos_down_lengths, pivot_length_1)
    array.push(bos_down_prices, broken_low_1)
    array.push(bos_down_bars, broken_low_bar_1)
    array.push(bos_down_dirs, last_breakout_dir_1[1])
    array.push(bos_down_colors, bos_down_color_1)
if bos_down_2 and ((last_breakout_dir_2[1] == 1 and show_choch) or (last_breakout_dir_2[1] != 1 and show_bos))
    array.push(bos_down_lengths, pivot_length_2)
    array.push(bos_down_prices, broken_low_2)
    array.push(bos_down_bars, broken_low_bar_2)
    array.push(bos_down_dirs, last_breakout_dir_2[1])
    array.push(bos_down_colors, bos_down_color_2)
if bos_down_3 and ((last_breakout_dir_3[1] == 1 and show_choch) or (last_breakout_dir_3[1] != 1 and show_bos))
    array.push(bos_down_lengths, pivot_length_3)
    array.push(bos_down_prices, broken_low_3)
    array.push(bos_down_bars, broken_low_bar_3)
    array.push(bos_down_dirs, last_breakout_dir_3[1])
    array.push(bos_down_colors, bos_down_color_3)
if bos_down_4 and ((last_breakout_dir_4[1] == 1 and show_choch) or (last_breakout_dir_4[1] != 1 and show_bos))
    array.push(bos_down_lengths, pivot_length_4)
    array.push(bos_down_prices, broken_low_4)
    array.push(bos_down_bars, broken_low_bar_4)
    array.push(bos_down_dirs, last_breakout_dir_4[1])
    array.push(bos_down_colors, bos_down_color_4)
if bos_down_5 and ((last_breakout_dir_5[1] == 1 and show_choch) or (last_breakout_dir_5[1] != 1 and show_bos))
    array.push(bos_down_lengths, pivot_length_5)
    array.push(bos_down_prices, broken_low_5)
    array.push(bos_down_bars, broken_low_bar_5)
    array.push(bos_down_dirs, last_breakout_dir_5[1])
    array.push(bos_down_colors, bos_down_color_5)
if bos_down_6 and ((last_breakout_dir_6[1] == 1 and show_choch) or (last_breakout_dir_6[1] != 1 and show_bos))
    array.push(bos_down_lengths, pivot_length_6)
    array.push(bos_down_prices, broken_low_6)
    array.push(bos_down_bars, broken_low_bar_6)
    array.push(bos_down_dirs, last_breakout_dir_6[1])
    array.push(bos_down_colors, bos_down_color_6)

// Process upward labels
int up_size = array.size(bos_up_lengths)
if up_size > 0
    array<float> unique_up_prices = array.new_float(0)
    for i = 0 to up_size - 1
        float p = array.get(bos_up_prices, i)
        if not array.includes(unique_up_prices, p)
            array.push(unique_up_prices, p)
    for j = 0 to array.size(unique_up_prices) - 1
        float curr_p = array.get(unique_up_prices, j)
        int max_len = 0
        int max_idx = -1
        for k = 0 to up_size - 1
            if array.get(bos_up_prices, k) == curr_p and array.get(bos_up_lengths, k) > max_len
                max_len := array.get(bos_up_lengths, k)
                max_idx := k
        if max_idx >= 0
            int the_bar = array.get(bos_up_bars, max_idx)
            int the_dir = array.get(bos_up_dirs, max_idx)
            color the_color = array.get(bos_up_colors, max_idx)
            if (the_dir == -1 and show_choch) or (the_dir != -1 and show_bos)
                string label_text = the_dir == -1 ? 'ChoCh ' + str.tostring(max_len) : 'BoS ' + str.tostring(max_len)
                label.new(bar_index[math.floor((bar_index - the_bar) / 2)], curr_p + bos_label_offset, label_text, color = color.new(color.white, 100), textcolor = text_color, size = size.small)

// Process downward labels
int down_size = array.size(bos_down_lengths)
if down_size > 0
    array<float> unique_down_prices = array.new_float(0)
    for i = 0 to down_size - 1
        float p = array.get(bos_down_prices, i)
        if not array.includes(unique_down_prices, p)
            array.push(unique_down_prices, p)
    for j = 0 to array.size(unique_down_prices) - 1
        float curr_p = array.get(unique_down_prices, j)
        int max_len = 0
        int max_idx = -1
        for k = 0 to down_size - 1
            if array.get(bos_down_prices, k) == curr_p and array.get(bos_down_lengths, k) > max_len
                max_len := array.get(bos_down_lengths, k)
                max_idx := k
        if max_idx >= 0
            int the_bar = array.get(bos_down_bars, max_idx)
            int the_dir = array.get(bos_down_dirs, max_idx)
            color the_color = array.get(bos_down_colors, max_idx)
            if (the_dir == 1 and show_choch) or (the_dir != 1 and show_bos)
                string label_text = the_dir == 1 ? 'ChoCh ' + str.tostring(max_len) : 'BoS ' + str.tostring(max_len)
                label.new(bar_index[math.floor((bar_index - the_bar) / 2)], curr_p - bos_label_offset, label_text, color = color.new(color.white, 100), textcolor = text_color, style = label.style_label_up, size = size.small)

// BoS triangles - toggled
plotshape(bos_up_1 and ((last_breakout_dir_1[1] == -1 and show_choch) or (last_breakout_dir_1[1] != -1 and show_bos)), style = shape.triangleup, location = location.belowbar, color = bos_up_color_1, size = size.tiny)
plotshape(bos_down_1 and ((last_breakout_dir_1[1] == 1 and show_choch) or (last_breakout_dir_1[1] != 1 and show_bos)), style = shape.triangledown, location = location.abovebar, color = bos_down_color_1, size = size.tiny)
plotshape(bos_up_2 and ((last_breakout_dir_2[1] == -1 and show_choch) or (last_breakout_dir_2[1] != -1 and show_bos)), style = shape.triangleup, location = location.belowbar, color = bos_up_color_2, size = size.tiny)
plotshape(bos_down_2 and ((last_breakout_dir_2[1] == 1 and show_choch) or (last_breakout_dir_2[1] != 1 and show_bos)), style = shape.triangledown, location = location.abovebar, color = bos_down_color_2, size = size.tiny)
plotshape(bos_up_3 and ((last_breakout_dir_3[1] == -1 and show_choch) or (last_breakout_dir_3[1] != -1 and show_bos)), style = shape.triangleup, location = location.belowbar, color = bos_up_color_3, size = size.tiny)
plotshape(bos_down_3 and ((last_breakout_dir_3[1] == 1 and show_choch) or (last_breakout_dir_3[1] != 1 and show_bos)), style = shape.triangledown, location = location.abovebar, color = bos_down_color_3, size = size.tiny)
plotshape(bos_up_4 and ((last_breakout_dir_4[1] == -1 and show_choch) or (last_breakout_dir_4[1] != -1 and show_bos)), style = shape.triangleup, location = location.belowbar, color = bos_up_color_4, size = size.tiny)
plotshape(bos_down_4 and ((last_breakout_dir_4[1] == 1 and show_choch) or (last_breakout_dir_4[1] != 1 and show_bos)), style = shape.triangledown, location = location.abovebar, color = bos_down_color_4, size = size.tiny)
plotshape(bos_up_5 and ((last_breakout_dir_5[1] == -1 and show_choch) or (last_breakout_dir_5[1] != -1 and show_bos)), style = shape.triangleup, location = location.belowbar, color = bos_up_color_5, size = size.tiny)
plotshape(bos_down_5 and ((last_breakout_dir_5[1] == 1 and show_choch) or (last_breakout_dir_5[1] != 1 and show_bos)), style = shape.triangledown, location = location.abovebar, color = bos_down_color_5, size = size.tiny)
plotshape(bos_up_6 and ((last_breakout_dir_6[1] == -1 and show_choch) or (last_breakout_dir_6[1] != -1 and show_bos)), style = shape.triangleup, location = location.belowbar, color = bos_up_color_6, size = size.tiny)
plotshape(bos_down_6 and ((last_breakout_dir_6[1] == 1 and show_choch) or (last_breakout_dir_6[1] != 1 and show_bos)), style = shape.triangledown, location = location.abovebar, color = bos_down_color_6, size = size.tiny)

// Alerts for BoS and ChoCh
alertcondition(bos_up_1 and last_breakout_dir_1[1] == -1 and show_choch, title = 'ChoCh Up Pivot 1', message = 'ChoCh Up detected for Pivot 1 at price {{close}}')
alertcondition(bos_up_1 and last_breakout_dir_1[1] != -1 and show_bos, title = 'BoS Up Pivot 1', message = 'BoS Up detected for Pivot 1 at price {{close}}')
alertcondition(bos_down_1 and last_breakout_dir_1[1] == 1 and show_choch, title = 'ChoCh Down Pivot 1', message = 'ChoCh Down detected for Pivot 1 at price {{close}}')
alertcondition(bos_down_1 and last_breakout_dir_1[1] != 1 and show_bos, title = 'BoS Down Pivot 1', message = 'BoS Down detected for Pivot 1 at price {{close}}')
alertcondition(bos_up_2 and last_breakout_dir_2[1] == -1 and show_choch, title = 'ChoCh Up Pivot 2', message = 'ChoCh Up detected for Pivot 2 at price {{close}}')
alertcondition(bos_up_2 and last_breakout_dir_2[1] != -1 and show_bos, title = 'BoS Up Pivot 2', message = 'BoS Up detected for Pivot 2 at price {{close}}')
alertcondition(bos_down_2 and last_breakout_dir_2[1] == 1 and show_choch, title = 'ChoCh Down Pivot 2', message = 'ChoCh Down detected for Pivot 2 at price {{close}}')
alertcondition(bos_down_2 and last_breakout_dir_2[1] != 1 and show_bos, title = 'BoS Down Pivot 2', message = 'BoS Down detected for Pivot 2 at price {{close}}')
alertcondition(bos_up_3 and last_breakout_dir_3[1] == -1 and show_choch, title = 'ChoCh Up Pivot 3', message = 'ChoCh Up detected for Pivot 3 at price {{close}}')
alertcondition(bos_up_3 and last_breakout_dir_3[1] != -1 and show_bos, title = 'BoS Up Pivot 3', message = 'BoS Up detected for Pivot 3 at price {{close}}')
alertcondition(bos_down_3 and last_breakout_dir_3[1] == 1 and show_choch, title = 'ChoCh Down Pivot 3', message = 'ChoCh Down detected for Pivot 3 at price {{close}}')
alertcondition(bos_down_3 and last_breakout_dir_3[1] != 1 and show_bos, title = 'BoS Down Pivot 3', message = 'BoS Down detected for Pivot 3 at price {{close}}')
alertcondition(bos_up_4 and last_breakout_dir_4[1] == -1 and show_choch, title = 'ChoCh Up Pivot 4', message = 'ChoCh Up detected for Pivot 4 at price {{close}}')
alertcondition(bos_up_4 and last_breakout_dir_4[1] != -1 and show_bos, title = 'BoS Up Pivot 4', message = 'BoS Up detected for Pivot 4 at price {{close}}')
alertcondition(bos_down_4 and last_breakout_dir_4[1] == 1 and show_choch, title = 'ChoCh Down Pivot 4', message = 'ChoCh Down detected for Pivot 4 at price {{close}}')
alertcondition(bos_down_4 and last_breakout_dir_4[1] != 1 and show_bos, title = 'BoS Down Pivot 4', message = 'BoS Down detected for Pivot 4 at price {{close}}')
alertcondition(bos_up_5 and last_breakout_dir_5[1] == -1 and show_choch, title = 'ChoCh Up Pivot 5', message = 'ChoCh Up detected for Pivot 5 at price {{close}}')
alertcondition(bos_up_5 and last_breakout_dir_5[1] != -1 and show_bos, title = 'BoS Up Pivot 5', message = 'BoS Up detected for Pivot 5 at price {{close}}')
alertcondition(bos_down_5 and last_breakout_dir_5[1] == 1 and show_choch, title = 'ChoCh Down Pivot 5', message = 'ChoCh Down detected for Pivot 5 at price {{close}}')
alertcondition(bos_down_5 and last_breakout_dir_5[1] != 1 and show_bos, title = 'BoS Down Pivot 5', message = 'BoS Down detected for Pivot 5 at price {{close}}')
alertcondition(bos_up_6 and last_breakout_dir_6[1] == -1 and show_choch, title = 'ChoCh Up Pivot 6', message = 'ChoCh Up detected for Pivot 6 at price {{close}}')
alertcondition(bos_up_6 and last_breakout_dir_6[1] != -1 and show_bos, title = 'BoS Up Pivot 6', message = 'BoS Up detected for Pivot 6 at price {{close}}')
alertcondition(bos_down_6 and last_breakout_dir_6[1] == 1 and show_choch, title = 'ChoCh Down Pivot 6', message = 'ChoCh Down detected for Pivot 6 at price {{close}}')
alertcondition(bos_down_6 and last_breakout_dir_6[1] != 1 and show_bos, title = 'BoS Down Pivot 6', message = 'BoS Down detected for Pivot 6 at price {{close}}')