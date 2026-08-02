n=int(input())
for _ in  range(n):
    l=int(input())
    s=input()
    m=0
    c=0
    for i in s:
        if i=='#':
            c+=1
        else:
            m=max(c,m)
            c=0
    m=max(c,m)
        
    print((m+1)//2)