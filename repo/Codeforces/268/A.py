n=int(input())
mat=[list(map(int,input().split())) for _ in range(n)]
c=0
for i in range(n):
    for j in range(n):
        if i!=j  and mat[i][0]==mat[j][1] :
            c+=1
print(c)