"""
本程序只做api演示，可能存在bug（确实存在bug）
有些特殊测试用例可能过不了
不必在意这些细节

"""




import math
import os
import sys
from time import sleep

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from desmos_writer_pack import open_desmos, write_expression, write_expression_api

def f(x):
    return 5*math.cos(x/5)

def compute_function_list(x,y,num):
    function_list = []
    for i in range(num//2):
        if f(x)>y:
            function_list.append(f"x={x}\\{{{str(y)}<y<{str(f(x))}\\}}")
            y = f(x)
        elif f(x)<y:
            function_list.append(f"x={x}\\{{{str(y)}>y>{str(f(x))}\\}}")
            y = f(x)
        if x>y:
            function_list.append(f"y={y}\\{{{str(y)}<x<{str(x)}\\}}")
            x=y
        elif x<y:
            function_list.append(f"y={y}\\{{{str(x)}<x<{str(y)}\\}}")
            x=y
    return function_list


if __name__ == '__main__':
    s = open_desmos(keep_open=True)
    sleep(1)
    write_expression_api(s, 1, r"y=5\cos(x/5)")
    print(1)
    write_expression_api(s, 2, "y=x")
    print(1)
    start = -10

    amount = 100

    functions = compute_function_list(int(start),0,amount)
    for i in range(amount):
        write_expression_api(s, i+3, functions[i])
        print(functions[i])

    s.close()


