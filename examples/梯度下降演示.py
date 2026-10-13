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

a=2


amount = 20

def f(x):
    return 0.1*x**2

def next_x(x):
    return x-2*x*a



def compute_function_list(x,y,num,a):
    function_list = []
    x1 = x
    y1 = y
    for i in range(num):
        x2 = x1 - 0.2*x1*a
        y2 = f(x2)
        k = (f(x2)-f(x1))/(x2-x1)
        b = y2-k*x2
        func = f"y = {k}x + {b}\\{{{min(x1,x2)}<x<{max(x1,x2)}\\}}"
        function_list.append(func)
        x1 = x2
        y1 = y2
    return function_list
if __name__ =='__main__':
    start = int(input("请输入起始横坐标"))
    functions = compute_function_list(start,f(start),amount,a)
    s = open_desmos(keep_open=True)
    write_expression_api(s,1,"y=0.1x^2")
    for i in range(amount):
        write_expression_api(s,i+2,functions[i])

    s.close()


